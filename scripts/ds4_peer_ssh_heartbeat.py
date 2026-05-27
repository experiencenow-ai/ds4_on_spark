#!/usr/bin/env python3
"""Tiny Spark quorum trim monitor."""
import argparse,json,os,shlex,socket,subprocess,time,urllib.request
from pathlib import Path
PEERS = ",".join("spark%d" % i for i in range(8)); PORTS = "8000,18000,18100,18101,18110"; VOTES = "~/.ds4-rescue/peer-trim-votes"; STATE = "~/.ds4-rescue/trim-state"
QUERY = "mode=abort&reset_external=true&release_offload_memory=true&malloc_trim=true&resume=true"
SWAP_KIB = 8 * 1024 * 1024; COOLDOWN = 300
def safe(s): return("".join(c for c in str(s) if c.isalnum() or c in "-_") or "unknown")
def run(argv,timeout,stdin=None):
    started = time.time()
    try:
        cp = subprocess.run(argv,input=stdin,text=True,capture_output=True,timeout=timeout)
        return({"rc":cp.returncode,"out":cp.stdout[-300:],"err":cp.stderr[-300:],"sec":round(time.time() - started,3)})
    except Exception as exc:
        return({"err":repr(exc),"sec":round(time.time() - started,3)})
def ssh(target,script,timeout,stdin=None):
    t = str(max(1,int(timeout)))
    opts = ["-o","BatchMode=yes","-o","ConnectTimeout=%s" % t,"-o","ServerAliveInterval=2","-o","ServerAliveCountMax=1","-o","StrictHostKeyChecking=no","-o","UserKnownHostsFile=/dev/null"]
    return(run(["ssh"] + opts + [target,script],timeout + 2,stdin))
def parse_peers(raw,observer):
    out,aliases = {},{observer,socket.gethostname(),socket.gethostname().split(".")[0]}
    for item in raw.replace(";",",").split(","):
        item = item.strip()
        if item == "":
            continue
        label,target = item.split("=",1) if "=" in item else (item.split("@",1)[0] if "@" in item else item,item)
        label = safe(label)
        if label not in aliases:
            out.setdefault(label,target.strip())
    return(list(out.items()))
def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True); tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj,sort_keys=True) + "\n",encoding="utf-8"); tmp.replace(path)
def probe(target,timeout):
    r = ssh(target,"printf ds4-ok",timeout); r["ok"] = r.get("rc") == 0 and "ds4-ok" in str(r.get("out",""))
    return(r)
def push_vote(target,observer,ballot,timeout):
    root = ".ds4-rescue/peer-trim-votes"; tmp = shlex.quote("%s/%s.json.tmp" % (root,safe(observer))); dst = shlex.quote("%s/%s.json" % (root,safe(observer)))
    return(ssh(target,"mkdir -p %s && cat > %s && mv %s %s" % (shlex.quote(root),tmp,tmp,dst),timeout,json.dumps(ballot,sort_keys=True) + "\n"))
def load_votes(root,max_age):
    now,out = int(time.time()),[]
    for path in root.glob("*.json") if root.exists() else []:
        try:
            vote = json.loads(path.read_text(encoding="utf-8"))
            if (now - int(vote.get("checked_at_unix",0))) <= max_age:
                out.append(vote)
        except Exception:
            pass
    return(out)
def quorum_threshold(n): return(max(1,(2 * max(1,n)) // 3))
def quorum(peer,votes,n):
    voters = sorted({safe(v.get("observer","")) for v in votes if not v.get("targets",{}).get(peer,{"ssh_exec_ok":True}).get("ssh_exec_ok",True)})
    need = quorum_threshold(n)
    return({"met":len(voters) >= need,"votes":len(voters),"threshold":need,"cluster_size":n,"voters":voters})
def trim_urls(target,ports=PORTS):
    host = "127.0.0.1" if target == "local" else target.rsplit("@",1)[-1]
    host = host[1:].split("]",1)[0] if host.startswith("[") and "]" in host else (host.rsplit(":",1)[0] if host.count(":") == 1 else host)
    return(["http://%s:%s/v1/trim_memory?%s" % (host,p.strip(),QUERY) for p in ports.replace(";",",").split(",") if p.strip().isdigit()])
def post(url,timeout):
    started = time.time()
    try:
        resp = urllib.request.urlopen(urllib.request.Request(url,method="POST"),timeout=timeout)
        return({"ok":200 <= resp.status < 300,"status":resp.status,"body":resp.read(300).decode("utf-8","replace"),"sec":round(time.time() - started,3)})
    except Exception as exc:
        return({"ok":False,"err":repr(exc),"sec":round(time.time() - started,3)})
def trim(label,target,reason,timeout):
    state = Path(STATE).expanduser() / ("%s.json" % safe(label))
    try:
        if (time.time() - float(json.loads(state.read_text()).get("at",0))) < COOLDOWN:
            return({"attempted":False,"skipped":"cooldown","reason":reason})
    except Exception:
        pass
    results = [{"url":url,**post(url,timeout)} for url in trim_urls(target)]
    save(state,{"at":int(time.time()),"target":target,"reason":reason,"results":results})
    return({"attempted":True,"ok":any(r.get("ok") for r in results),"reason":reason,"results":results})
def swap_used_kib():
    vals = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith(("SwapTotal:","SwapFree:")):
                vals[line.split(":")[0]] = int(line.split()[1])
    except Exception:
        return(0)
    return(max(0,vals.get("SwapTotal",0) - vals.get("SwapFree",0)))
def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--node", default=os.environ.get("USER","") or socket.gethostname().split(".")[0]); p.add_argument("--peers", default=PEERS); p.add_argument("--timeout", type=float, default=5.0); p.add_argument("--vote-seconds", type=int, default=180); p.add_argument("--no-remote-trim", action="store_true")
    args = p.parse_args(); me = safe(args.node); peers = parse_peers(args.peers,me); root = Path(VOTES).expanduser()
    status = {peer:{"target":target,"ssh_exec_ok":probe(target,args.timeout).get("ok",False)} for peer,target in peers}
    ballot = {"schema":"ds4.peer_trim_ballot.v1","observer":me,"checked_at_unix":int(time.time()),"targets":status}; save(root / ("%s.json" % me),ballot)
    pushes = {peer:push_vote(status[peer]["target"],me,ballot,args.timeout) for peer in status if status[peer]["ssh_exec_ok"]}
    votes,remote = load_votes(root,args.vote_seconds),{}
    for peer,target in peers:
        reason = quorum(peer,votes,len(peers) + 1); remote[peer] = trim("remote-%s" % peer,target,reason,args.timeout) if reason["met"] and not args.no_remote_trim else {"attempted":False,"skipped":"quorum","reason":reason}
    used = swap_used_kib(); local_reason = {"swap_used_kib":used,"threshold_kib":SWAP_KIB}
    local = trim("self","local",local_reason,args.timeout) if used >= SWAP_KIB else {"attempted":False,"reason":local_reason}
    print(json.dumps({"schema":"ds4.quorum_trim.run.v1","observer":me,"status":status,"pushes":pushes,"remote_trims":remote,"self_trim":local},sort_keys=True),flush=True)
    return(0)
if __name__ == "__main__":
    raise SystemExit(main())
