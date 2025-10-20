from strands.models import BedrockModel

nova_pro = BedrockModel(
    model_id="amazon.nova-pro-v1:0",
    region_name="us-east-1",
    temperature=0.3
)

nova_lite = BedrockModel(
    model_id="us.amazon.nova-lite-v1:0",
    region_name="us-east-1", 
    temperature=0.3
)

nova_premier = BedrockModel(
    model_id="us.amazon.nova-premier-v1:0",
    region_name="us-east-1",
    temperature=0.2
)

nova_micro = BedrockModel(
    model_id="us.amazon.nova-micro-v1:0",
    region_name="us-east-1",
    temperature=0.3
)

nova_sonic = BedrockModel(
    model_id="us.amazon.nova-sonic-v1:0",
    region_name="us-east-1",
    temperature=0.7
)