import os
from langchain_aws import ChatBedrock

# AWS Configuration
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID", 
    "anthropic.claude-3-5-sonnet-20241022-v2:0"  # Fallback to Claude 3.5 Sonnet
)

# Initialize AWS Bedrock client
def get_bedrock_llm(temperature: float = 0.5):
    return ChatBedrock(
        model_id=BEDROCK_MODEL_ID,
        region_name=AWS_REGION,
        model_kwargs={"temperature": temperature}
    )
