#!/usr/bin/env python3

import json
import os
import sys
from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures" / "model_contract" / "deepseek_v4_flash"
ORACLE_DIR = FIX / "oracle"


def load_json(path: Path) -> Any:
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


def write_json(path: Path, data: Any) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", encoding="utf-8") as f:
		json.dump(data, f, indent=2, sort_keys=True)
		f.write("\n")


def init_dist() -> tuple[int, int, int]:
	world_size = int(os.getenv("WORLD_SIZE", "1"))
	rank = int(os.getenv("RANK", "0"))
	local_rank = int(os.getenv("LOCAL_RANK", "0"))
	if world_size > 1:
		import torch.distributed as dist
		if not dist.is_initialized():
			dist.init_process_group("nccl")
	return world_size, rank, local_rank


def sha256_file(path: Path) -> str:
	h = sha256()
	with path.open("rb") as f:
		for chunk in iter(lambda: f.read(1024 * 1024), b""):
			h.update(chunk)
	return h.hexdigest()


def try_version(modname: str) -> str:
	try:
		m = __import__(modname)
		return str(getattr(m, "__version__", "unknown"))
	except Exception:
		return "missing"


def suppress_print_for_nonzero_rank(rank: int) -> None:
	if rank != 0:
		builtins = __import__("builtins")
		builtins.print = lambda *_, **__: None


def reset_model_state(model) -> None:
	# The upstream reference model caches KV + compressor state inside module buffers.
	import torch

	neg_inf = float("-inf")
	for m in model.modules():
		if hasattr(m, "kv_cache") and isinstance(getattr(m, "kv_cache"), torch.Tensor):
			m.kv_cache.zero_()
		if hasattr(m, "compressor"):
			comp = getattr(m, "compressor")
			if comp is not None:
				if hasattr(comp, "kv_state") and isinstance(getattr(comp, "kv_state"), torch.Tensor):
					comp.kv_state.zero_()
				if hasattr(comp, "score_state") and isinstance(getattr(comp, "score_state"), torch.Tensor):
					comp.score_state.fill_(neg_inf)
				# Force lazy pointer rebind on next forward.
				if hasattr(comp, "kv_cache"):
					comp.kv_cache = None
		if hasattr(m, "indexer"):
			idx = getattr(m, "indexer")
			if idx is not None:
				if hasattr(idx, "kv_cache") and isinstance(getattr(idx, "kv_cache"), torch.Tensor):
					idx.kv_cache.zero_()
				if hasattr(idx, "compressor") and idx.compressor is not None:
					ic = idx.compressor
					if hasattr(ic, "kv_state") and isinstance(getattr(ic, "kv_state"), torch.Tensor):
						ic.kv_state.zero_()
					if hasattr(ic, "score_state") and isinstance(getattr(ic, "score_state"), torch.Tensor):
						ic.score_state.fill_(neg_inf)
					if hasattr(ic, "kv_cache"):
						ic.kv_cache = None


def topk_trace(logits, k: int) -> dict[str, Any]:
	import torch

	# logits: [vocab]
	vals, idxs = torch.topk(logits.float().cpu(), k=min(k, int(logits.numel())))
	return {
		"argmax_id": int(idxs[0].item()),
		"topk_ids": [int(x) for x in idxs.tolist()],
		"topk_logits": [float(x) for x in vals.tolist()],
	}


def main() -> int:
	parser = ArgumentParser()
	parser.add_argument("--ckpt-path", type=str, required=True, help="Converted checkpoint directory with model{rank}-mp{mp}.safetensors and tokenizer files.")
	parser.add_argument("--config", type=str, default=str(FIX / "inference" / "config.json"), help="Reference inference config JSON (defaults to pinned fixture).")
	parser.add_argument("--prompts", type=str, default=str(ORACLE_DIR / "prompts.json"), help="Oracle prompt cases JSON.")
	parser.add_argument("--out", type=str, default=str(ORACLE_DIR / "logits_oracle.json"), help="Output oracle JSON path (commit only after review).")
	parser.add_argument("--steps", type=int, default=8, help="Number of decode steps to record per case (defaults to max_new_tokens from prompts).")
	args = parser.parse_args()

	world_size, rank, local_rank = init_dist()
	suppress_print_for_nonzero_rank(rank)

	try:
		import torch
		from safetensors.torch import load_model
		from transformers import AutoTokenizer
	except Exception as e:
		print(f"ERROR: missing runtime deps (torch/transformers/safetensors): {e}")
		return 2

	if not torch.cuda.is_available():
		print("ERROR: CUDA is required to generate V4 Flash logits oracles.")
		return 2

	ckpt_path = Path(args.ckpt_path)
	weights_path = ckpt_path / f"model{rank}-mp{world_size}.safetensors"
	if not weights_path.exists():
		print(f"ERROR: missing converted weights file: {weights_path}")
		print("Refusing to download weights. Provide a local converted checkpoint directory.")
		return 2

	# Import pinned upstream reference code from fixtures.
	sys.path.insert(0, str(FIX / "inference"))
	sys.path.insert(0, str(FIX / "encoding"))
	from model import Transformer, ModelArgs  # type: ignore
	from encoding_dsv4 import encode_messages  # type: ignore

	cfg = load_json(Path(args.config))
	model_args = ModelArgs(**cfg)

	torch.cuda.set_device(local_rank)
	torch.cuda.memory._set_allocator_settings("expandable_segments:True")
	torch.set_default_dtype(torch.bfloat16)
	torch.set_num_threads(8)
	torch.manual_seed(33377335)

	with torch.device("cuda"):
		model = Transformer(model_args)

	tokenizer = AutoTokenizer.from_pretrained(str(ckpt_path))
	missing, unexpected = load_model(model, str(weights_path), strict=False)
	if rank == 0:
		print(f"loaded weights: missing={len(missing)} unexpected={len(unexpected)}")

	prompts = load_json(Path(args.prompts))
	cases = list(prompts.get("cases", []))
	if not cases:
		print("ERROR: prompts.json has no cases")
		return 2

	default_topk = int(prompts.get("default_topk", 64))
	upstream_commit = (FIX / "upstream_commit.txt").read_text(encoding="utf-8").strip() if (FIX / "upstream_commit.txt").exists() else ""

	ckpt_tokenizer_json = ckpt_path / "tokenizer.json"
	ckpt_tokenizer_cfg = ckpt_path / "tokenizer_config.json"
	tokenizer_sha = {}
	if ckpt_tokenizer_json.exists():
		tokenizer_sha["tokenizer.json"] = sha256_file(ckpt_tokenizer_json)
	if ckpt_tokenizer_cfg.exists():
		tokenizer_sha["tokenizer_config.json"] = sha256_file(ckpt_tokenizer_cfg)

	results: dict[str, Any] = {
		"format_version": 1,
		"upstream_commit": upstream_commit,
		"reference": {
			"inference_config": str(Path(args.config).name),
			"model_args": {
				"max_batch_size": int(model_args.max_batch_size),
				"max_seq_len": int(model_args.max_seq_len),
				"n_layers": int(model_args.n_layers),
				"compress_ratios_len": int(len(getattr(model_args, "compress_ratios", []))),
				"window_size": int(model_args.window_size),
			},
		},
		"runtime_versions": {
			"python": sys.version.split()[0],
			"torch": try_version("torch"),
			"transformers": try_version("transformers"),
			"safetensors": try_version("safetensors"),
		},
		"tokenizer_sha256": tokenizer_sha,
		"world_size": world_size,
		"seed": 33377335,
		"cases": [],
	}

	for case in cases:
		reset_model_state(model)
		case_id = case.get("id", "")
		thinking_mode = case.get("thinking_mode", "chat")
		max_new_tokens = int(case.get("max_new_tokens", args.steps))
		steps = min(max_new_tokens, int(args.steps))
		temperature = float(case.get("temperature", 0.0))
		topk = int(case.get("topk", default_topk))
		messages = case.get("messages", [])

		prompt = encode_messages(messages, thinking_mode=thinking_mode)
		prompt_tokens = tokenizer.encode(prompt)

		# Run the upstream-style generation loop, but record logits at each step.
		total_len = min(model.max_seq_len, len(prompt_tokens) + steps)
		tokens = torch.full((1, total_len), -1, dtype=torch.long, device="cuda")
		tokens[0, :len(prompt_tokens)] = torch.tensor(prompt_tokens, dtype=torch.long, device="cuda")

		trace: list[dict[str, Any]] = []
		prev_pos = 0
		for cur_pos in range(len(prompt_tokens), total_len):
			logits = model.forward(tokens[:, prev_pos:cur_pos], prev_pos)[0]
			trace_entry = {"cur_pos": int(cur_pos), "start_pos": int(prev_pos)}
			trace_entry.update(topk_trace(logits, topk))
			trace.append(trace_entry)

			# Deterministic decode: temperature=0 uses argmax.
			if temperature > 0:
				# Keep the sampling path available but note: this is not deterministic across kernels.
				probs = torch.softmax(logits / max(temperature, 1e-5), dim=-1, dtype=torch.float32)
				next_token = probs.div_(torch.empty_like(probs).exponential_(1)).argmax(dim=-1)
			else:
				next_token = logits.argmax(dim=-1)

			tokens[0, cur_pos] = next_token
			prev_pos = cur_pos

		if rank == 0:
			results["cases"].append(
				{
					"id": case_id,
					"thinking_mode": thinking_mode,
					"prompt_tokens": [int(x) for x in prompt_tokens],
					"trace": trace,
				}
			)
			print(f"case {case_id}: prompt_tokens={len(prompt_tokens)} steps={len(trace)}")

	if rank == 0:
		write_json(Path(args.out), results)
		print(f"OK: wrote oracle to {args.out}")

	return 0


if __name__ == "__main__":
	raise SystemExit(main())
