"""Run the BFCL CLI against the local llama-server endpoint.

Registers each profile name passed in BFCL_LOCAL_MODELS (comma separated) as a
function-calling model served through the OpenAI chat completions handler, then
delegates to the regular `bfcl` CLI.
"""

import os
import sys

from bfcl_eval.constants.model_config import MODEL_CONFIG_MAPPING, ModelConfig
from bfcl_eval.model_handler.api_inference.openai_completion import (
    OpenAICompletionsHandler,
)

os.environ.setdefault("OPENAI_BASE_URL", "http://127.0.0.1:18080/v1")
os.environ.setdefault("OPENAI_API_KEY", "local")

for name in filter(None, os.environ.get("BFCL_LOCAL_MODELS", "").split(",")):
    MODEL_CONFIG_MAPPING[name] = ModelConfig(
        model_name=name,
        display_name=f"{name} (FC, local)",
        url="http://127.0.0.1:18080/v1",
        org="local-llm-agent-lab",
        license="local",
        model_handler=OpenAICompletionsHandler,
        input_price=None,
        output_price=None,
        is_fc_model=True,
        underscore_to_dot=True,
    )

from bfcl_eval.__main__ import cli  # noqa: E402

sys.exit(cli())
