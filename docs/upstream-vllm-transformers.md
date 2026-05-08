# Upstreams: vLLM + Transformers

These are tracked as “runtime + reference” components for Spark deployment work.

## vLLM

- Repo: `https://github.com/vllm-project/vllm`
- Ref: `refs/tags/v0.20.2`
- Commit: `bc150f50299199599673614f80d12a196f377655`
- License: Apache-2.0 (see upstream `LICENSE`)

Fetch:

```bash
./scripts/fetch_upstreams.sh vllm
```

## Transformers

- Repo: `https://github.com/huggingface/transformers`
- Ref: `refs/tags/v5.8.0`
- Commit: `a9e70365af64e028d40d8c7909deb7f138b49857`
- License: Apache-2.0 (see upstream `LICENSE`)

Fetch:

```bash
./scripts/fetch_upstreams.sh transformers
```

