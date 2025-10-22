# Technology Stack & Build System

## Core Technologies
- **Backend Framework**: Flask with SocketIO for real-time communication
- **AI/ML Platform**: AWS Bedrock with Amazon Nova models (Pro, Lite, Premier, Micro, Sonic)
- **Agent Framework**: Strands Agents for multi-agent orchestration
- **Cloud Platform**: AWS (S3, Bedrock, AgentCore)
- **Container Runtime**: Docker with UV package manager
- **Document Processing**: PyPDF2, python-docx, openpyxl for file extraction
- **Policy Generation**: ReportLab for PDF creation

## Key Dependencies
- **bedrock-agentcore**: Core agent runtime and memory management
- **strands-agents**: Multi-agent workflow orchestration
- **Flask-SocketIO**: Real-time WebSocket communication
- **boto3**: AWS SDK for Python
- **PyPDF2**: PDF document processing
- **reportlab**: PDF policy document generation

## Build & Development Commands

### Local Development
```bash
# Install dependencies
uv pip install -r requirements.txt

# Run Flask development server
python run.py

# Run AgentCore locally
python agentcore_main.py
```

### Docker Build & Deploy
```bash
# Build container
docker build -t nyl-underwriting .

# Run container
docker run -p 8080:8080 -p 8000:8000 nyl-underwriting

# Deploy to AgentCore
agentcore deploy
```

### Testing & Validation
```bash
# Health check endpoint
curl http://localhost:8080/health

# Test AgentCore invoke
agentcore invoke '{"request_type": "create_session"}'
```

## Environment Configuration
- **AWS_REGION**: us-east-1 (default)
- **S3_BUCKET**: nyl-underwriting-documents-121409194654
- **DOCKER_CONTAINER**: Set to 1 when running in container