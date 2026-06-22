import os
from langchain_aws import ChatBedrock

# AWS Configuration
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
BEDROCK_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID", 
    "apac.anthropic.claude-3-5-sonnet-20241022-v2:0"  # AP-South cross-region inference profile
)

# Initialize AWS Bedrock client
def get_bedrock_llm(temperature: float = 0.5):
    return ChatBedrock(
        model_id=BEDROCK_MODEL_ID,
        region_name=AWS_REGION,
        model_kwargs={"temperature": temperature}
    )
