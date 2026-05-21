# Small Model Transformers Qualification Results

Batch timestamp: `2026-05-21T13:59:37.278660Z`
Hardware node: `spark2`
Records: `27` of `64` inventory entries
Executed records: `16`
Failures: `11`
Wall clock seconds: `2742.084`

## Combined Product Impact
- #1214 baseline: `37` llama.cpp/GGUF executed records and `27` transformers entries blocked as unwired.
- This run replaces the `27` unwired transformer placeholders with `16` executed transformer records and `11` concrete runtime failure records.
- Current Spark2 inventory coverage: `53` of `64` entries have executed generation records; `11` of `64` remain runtime-failed.

## Top 3 By Quality
- `hf-Qwen-Qwen3.5-2B` pass_rate=1.0
- `hf-zai-org-SWE-Dev-7B` pass_rate=1.0
- `hf-zai-org-SWE-Dev-32B` pass_rate=1.0

## Top 3 By Mean Tok/s
- `hf-deepseek-ai-DeepSeek-R1-Distill-Qwen-1.5B` mean_tok_s=40.747303634839035
- `hf-Qwen-Qwen3.5-0.8B` mean_tok_s=40.21930060317706
- `hf-Qwen-Qwen3.5-2B` mean_tok_s=24.793756596290248

## Top 3 By Cost Proxy
- `hf-Qwen-Qwen3.5-0.8B` cost_proxy=1.0666666666666667
- `hf-Qwen-Qwen3.5-2B` cost_proxy=2.0
- `hf-deepseek-ai-DeepSeek-R1-Distill-Qwen-1.5B` cost_proxy=3.0

## Failed Models
- `hf-Qwen-Qwen3.5-35B-A3B-GPTQ-Int4`: qualification failed: transformers qualification command failed rc=1 stderr=ss.from_pretrained(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/modeling_utils.py", line 4181, in from_pretrained
    hf_quantizer, config, device_map = get_hf_quantizer(
                                       ^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/quantizers/auto.py", line 334, in get_hf_quantizer
    hf_quantizer = AutoHfQuantizer.from_config(
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/quantizers/auto.py", line 211, in from_config
    return target_cls(quantization_config, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/quantizers/quantizer_gptq.py", line 53, in __init__
    raise ImportError("Loading a GPTQ quantized model requires optimum (`pip install optimum`)")
ImportError: Loading a GPTQ quantized model requires optimum (`pip install optimum`)
- `hf-Qwen-Qwen3.6-35B-A3B-FP8`: qualification failed: transformers qualification command failed rc=1 stderr=Traceback (most recent call last):
  File "<string>", line 11, in <module>
  File "/usr/local/lib/python3.12/dist-packages/transformers/models/auto/auto_factory.py", line 405, in from_pretrained
    return model_class.from_pretrained(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/modeling_utils.py", line 4181, in from_pretrained
    hf_quantizer, config, device_map = get_hf_quantizer(
                                       ^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/quantizers/auto.py", line 342, in get_hf_quantizer
    hf_quantizer.validate_environment(
  File "/usr/local/lib/python3.12/dist-packages/transformers/quantizers/quantizer_finegrained_fp8.py", line 32, in validate_environment
    raise ImportError("Loading an FP8 quantized model requires accelerate (`pip install accelerate`)")
ImportError: Loading an FP8 quantized model requires accelerate (`pip install accelerate`)
- `hf-moonshotai-Moonlight-16B-A3B-Instruct`: qualification failed: transformers qualification command failed rc=1 stderr=c_module_utils.py", line 627, in get_class_from_dynamic_module
    return get_class_in_module(class_name, final_module, force_reload=force_download)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/dynamic_module_utils.py", line 309, in get_class_in_module
    module_spec.loader.exec_module(module)
  File "<frozen importlib._bootstrap_external>", line 995, in exec_module
  File "<frozen importlib._bootstrap>", line 488, in _call_with_frames_removed
  File "/root/.cache/huggingface/modules/transformers_modules/Moonlight_hyphen_16B_hyphen_A3B_hyphen_Instruct/59fdd7213ce4d058/modeling_deepseek.py", line 57, in <module>
    from transformers.utils.import_utils import is_torch_fx_available
ImportError: cannot import name 'is_torch_fx_available' from 'transformers.utils.import_utils' (/usr/local/lib/python3.12/dist-packages/transformers/utils/import_utils.py). Did you mean: 'is_torch_available'?
- `hf-zai-org-SWE-Dev-9B`: qualification failed: transformers qualification command failed rc=1 stderr=:
  File "<string>", line 11, in <module>
  File "/usr/local/lib/python3.12/dist-packages/transformers/models/auto/auto_factory.py", line 390, in from_pretrained
    return model_class.from_pretrained(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/modeling_utils.py", line 4252, in from_pretrained
    model = cls(config, *model_args, **model_kwargs)
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/root/.cache/huggingface/modules/transformers_modules/SWE_hyphen_Dev_hyphen_9B/041b850d361b46d3/modeling_chatglm.py", line 918, in __init__
    self.max_sequence_length = config.max_length
                               ^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/configuration_utils.py", line 434, in __getattribute__
    return super().__getattribute__(key)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AttributeError: 'ChatGLMConfig' object has no attribute 'max_length'. Did you mean: 'seq_length'?
- `hf-Qwen-Qwen3.5-122B-A10B-GPTQ-Int4`: qualification failed: transformers qualification command failed rc=1 stderr=ss.from_pretrained(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/modeling_utils.py", line 4181, in from_pretrained
    hf_quantizer, config, device_map = get_hf_quantizer(
                                       ^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/quantizers/auto.py", line 334, in get_hf_quantizer
    hf_quantizer = AutoHfQuantizer.from_config(
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/quantizers/auto.py", line 211, in from_config
    return target_cls(quantization_config, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/quantizers/quantizer_gptq.py", line 53, in __init__
    raise ImportError("Loading a GPTQ quantized model requires optimum (`pip install optimum`)")
ImportError: Loading a GPTQ quantized model requires optimum (`pip install optimum`)
- `hf-mistralai-Devstral-Small-2-24B-Instruct-2512`: qualification failed: transformers qualification command failed rc=1 stderr=, MinistralConfig, Ministral3Config, MistralConfig, MixtralConfig, MllamaConfig, ModernBertDecoderConfig, MoshiConfig, MptConfig, MusicgenConfig, MusicgenMelodyConfig, MvpConfig, NanoChatConfig, NemotronConfig, NemotronHConfig, OlmoConfig, Olmo2Config, Olmo3Config, OlmoHybridConfig, OlmoeConfig, OpenAIGPTConfig, OPTConfig, PegasusConfig, PersimmonConfig, PhiConfig, Phi3Config, Phi4MultimodalConfig, PhimoeConfig, PLBartConfig, ProphetNetConfig, Qwen2Config, Qwen2MoeConfig, Qwen3Config, Qwen3_5Config, Qwen3_5MoeConfig, Qwen3_5MoeTextConfig, Qwen3_5TextConfig, Qwen3MoeConfig, Qwen3NextConfig, RecurrentGemmaConfig, ReformerConfig, RemBertConfig, RobertaConfig, RobertaPreLayerNormConfig, RoCBertConfig, RoFormerConfig, RwkvConfig, SeedOssConfig, SmolLM3Config, SolarOpenConfig, StableLmConfig, Starcoder2Config, TrOCRConfig, VaultGemmaConfig, WhisperConfig, XGLMConfig, XLMConfig, XLMRobertaConfig, XLMRobertaXLConfig, XLNetConfig, xLSTMConfig, XmodConfig, YoutuConfig, ZambaConfig, Zamba2Config.
- `hf-Qwen-Qwen3.6-27B-FP8`: qualification failed: transformers qualification command failed rc=1 stderr=Traceback (most recent call last):
  File "<string>", line 11, in <module>
  File "/usr/local/lib/python3.12/dist-packages/transformers/models/auto/auto_factory.py", line 405, in from_pretrained
    return model_class.from_pretrained(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/modeling_utils.py", line 4181, in from_pretrained
    hf_quantizer, config, device_map = get_hf_quantizer(
                                       ^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/quantizers/auto.py", line 342, in get_hf_quantizer
    hf_quantizer.validate_environment(
  File "/usr/local/lib/python3.12/dist-packages/transformers/quantizers/quantizer_finegrained_fp8.py", line 32, in validate_environment
    raise ImportError("Loading an FP8 quantized model requires accelerate (`pip install accelerate`)")
ImportError: Loading an FP8 quantized model requires accelerate (`pip install accelerate`)
- `hf-deepseek-ai-DeepSeek-V4-Flash`: qualification failed: transformers qualification command failed rc=1 stderr='attention_factor'}
Traceback (most recent call last):
  File "<string>", line 11, in <module>
  File "/usr/local/lib/python3.12/dist-packages/transformers/models/auto/auto_factory.py", line 405, in from_pretrained
    return model_class.from_pretrained(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/modeling_utils.py", line 4181, in from_pretrained
    hf_quantizer, config, device_map = get_hf_quantizer(
                                       ^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/quantizers/auto.py", line 342, in get_hf_quantizer
    hf_quantizer.validate_environment(
  File "/usr/local/lib/python3.12/dist-packages/transformers/quantizers/quantizer_finegrained_fp8.py", line 32, in validate_environment
    raise ImportError("Loading an FP8 quantized model requires accelerate (`pip install accelerate`)")
ImportError: Loading an FP8 quantized model requires accelerate (`pip install accelerate`)
- `hf-deepseek-ai-DeepSeek-V4-Flash-inference`: qualification failed: transformers qualification command failed rc=1 stderr=^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/configuration_utils.py", line 840, in from_dict
    config = cls(**config_dict)
             ^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/huggingface_hub/dataclasses.py", line 275, in init_with_validate
    initial_init(self, *args, **kwargs)  # type: ignore [call-arg]
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/huggingface_hub/dataclasses.py", line 190, in __init__
    self.__post_init__(**additional_kwargs)
  File "/usr/local/lib/python3.12/dist-packages/transformers/configuration_utils.py", line 254, in __post_init__
    self.dtype = getattr(torch, self.dtype)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/torch/__init__.py", line 2881, in __getattr__
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
AttributeError: module 'torch' has no attribute 'fp8'
- `hf-microsoft-Phi-4-mini-flash-reasoning`: qualification failed: transformers qualification command failed rc=1 stderr=ry.py", line 379, in from_pretrained
    model_class = get_class_from_dynamic_module(
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/dynamic_module_utils.py", line 616, in get_class_from_dynamic_module
    final_module = get_cached_module_file(
                   ^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/dynamic_module_utils.py", line 445, in get_cached_module_file
    modules_needed = check_imports(resolved_module_file)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/dynamic_module_utils.py", line 258, in check_imports
    raise ImportError(
ImportError: This modeling file requires the following packages that were not found in your environment: causal_conv1d, causal_conv1d_cuda, flash_attn, mamba_ssm, selective_scan_cuda. Run `pip install causal_conv1d causal_conv1d_cuda flash_attn mamba_ssm selective_scan_cuda`
- `hf-microsoft-Phi-4-mini-instruct`: qualification failed: transformers qualification command failed rc=1 stderr=           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/dynamic_module_utils.py", line 627, in get_class_from_dynamic_module
    return get_class_in_module(class_name, final_module, force_reload=force_download)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.12/dist-packages/transformers/dynamic_module_utils.py", line 309, in get_class_in_module
    module_spec.loader.exec_module(module)
  File "<frozen importlib._bootstrap_external>", line 995, in exec_module
  File "<frozen importlib._bootstrap>", line 488, in _call_with_frames_removed
  File "/root/.cache/huggingface/modules/transformers_modules/Phi_hyphen_4_hyphen_mini_hyphen_instruct/3886b25a63d271ee/modeling_phi3.py", line 37, in <module>
    from transformers.utils import (
ImportError: cannot import name 'LossKwargs' from 'transformers.utils' (/usr/local/lib/python3.12/dist-packages/transformers/utils/__init__.py)
