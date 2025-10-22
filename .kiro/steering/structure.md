# Project Structure & Organization

## Root Directory Structure
```
├── agentcore_main.py          # Main AgentCore entrypoint and NYLUnderwritingAgent class
├── run.py                     # Flask web server with SocketIO and routing
├── config.py                  # Configuration constants and business rules
├── models.py                  # Bedrock model definitions (Nova Pro/Lite/Premier/Micro/Sonic)
├── underwriting_agents.py     # 8-agent underwriting workflow implementation
├── nova_sonic_underwriting.py # Voice conversation handler for Nova Sonic
├── policy_generator.py        # PDF policy document generation
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Container build configuration
├── .bedrock_agentcore.yaml    # AgentCore deployment configuration
```

## Key Directories
- **templates/**: HTML templates for web interface
  - `index.html` - Main upload interface
  - `modern_chat_app.html` - Voice conversation interface
  - `login.html` - Authentication page
- **static/**: Frontend assets (CSS, JS, images)
- **uploads/**: Temporary file storage for document processing
- **sessions/**: Session-specific data storage

## Core Components

### AgentCore Integration (`agentcore_main.py`)
- **NYLUnderwritingAgent**: Main agent class handling all request types
- **Request routing**: s3_process, create_session, get_status, get_summary
- **S3 integration**: Document processing and status tracking
- **Error handling**: Comprehensive logging and fallback mechanisms

### Web Interface (`run.py`)
- **Flask routes**: Upload, status, policy download endpoints
- **SocketIO handlers**: Real-time updates and Nova Sonic integration
- **Session management**: UUID-based session tracking
- **File validation**: ZIP file processing and S3 upload

### Agent Workflow (`underwriting_agents.py`)
- **8-agent sequence**: data_intake → document_verification → medical_risk_assessment → financial → driving → compliance → lifestyle_behavioral → summary_generation
- **Context management**: Session-based data persistence
- **Document processing**: PDF extraction and analysis

## Configuration Patterns
- **Business rules**: Defined in `config.py` with structured dictionaries
- **Model configuration**: Centralized in `models.py` with consistent parameters
- **Environment variables**: AWS region, S3 bucket, container detection
- **Session isolation**: Each session gets dedicated S3 folder and processing context

## Data Flow
1. **Document Upload** → S3 storage with session-based keys
2. **AgentCore Processing** → 8-agent workflow execution
3. **Status Updates** → Real-time S3 JSON updates
4. **Policy Generation** → PDF creation and S3 storage
5. **Frontend Updates** → SocketIO real-time notifications