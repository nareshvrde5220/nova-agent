# 🧠 Agentic AI Based Policy Agent

**Team Name:**  Trianz D&AI Innovation Factory
**Solution Name:** Agentic AI Based Policy Agent  
**Version:** 1.0.0  
**Last Updated:** October 2025  

---

## 🩺 Overview
The **Agentic AI Based Policy Agent** is an intelligent, end-to-end underwriting and policy generation automation platform designed to reduce policy processing time from **7–14 days to just few minutes**.  
Built using **AWS Bedrock AgentCore**, **AWS Strands** and **Amazon Nova AI models**, it provides seamless **voice-based data intake**, automated **document analysis**, and instant **policy generation** through orchestrated multi-agent processing.

The live demo of this code is hosted on https://daiportal.trianz.com/nova-agent

---

## ⚙️ System Highlights
- **Voice-Enabled Underwriting:** Uses Amazon Nova Sonic for natural, conversational data collection.  
- **Multi-Agent Automation:** Eight specialized Nova Pro agents perform medical, financial, compliance, and lifestyle assessments in parallel.  
- **Real-Time Transparency:** Live status tracking and progress visualization for complete process visibility.  
- **Automated Policy Generation:** Produces professional, compliant Word documents instantly, stored securely on Amazon S3.  

---

## 🏗️ Architecture Overview
**Frontend (Flask + Socket.IO):** Provides an interactive web interface and real-time updates.  
**Voice Layer (Nova Sonic):** Collects applicant information through voice.  
**Processing Core (AWS Bedrock AgentCore):** Manages orchestration across eight Nova Pro agents:

1. Data Intake  
2. Document Verification  
3. Medical Assessment  
4. Financial Analysis  
5. Driving Analysis  
6. Compliance Check  
7. Lifestyle Analysis  
8. Summary Generation  


---

## ✨ Key Features
- Natural voice interaction for application intake  
- Parallel multi-agent processing for faster, accurate underwriting  
- Real-time tracking dashboard with status indicators  
- Automated policy document generation in Word format  
- Secure session management via isolated S3 storage  

---

## 🧰 Technical Stack
- **AWS Services:** Bedrock AgentCore, Bedrock Models, Nova Sonic, Nova Pro, S3, IAM  
- **Backend:** Python 3.10+, Flask, Boto3, Flask-SocketIO  
- **Frontend:** HTML5, CSS3, JavaScript, Bootstrap 5  
- **Tools:** Git, dotenv, asyncio, threading  

---

## 🚀 Installation Setup & Execution:

# 1. Clone the repository
git clone <repository-url>
cd <repository-folder>

# 2. Create and activate a virtual environment
python -m venv venv
# For macOS/Linux
source venv/bin/activate
# For Windows
venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure AWS credentials and S3 bucket name
# - Set up your AWS access key, secret key, and region in ~/.aws/credentials or using environment variables.
# - Update your S3 bucket name in the configuration file if required.

# 5. Run the application
# Go to the specific application directory and run:
python run.py

# 6. Access the application
# Open your browser and navigate to:
# Go to http://127.0.0.1:8080/login, enter valid credentials, and the main page will open.

## System Workflow
1. **Voice Intake:** Collects applicant data using *Nova Sonic*  
2. **Document Upload:** ZIP file sent to S3, triggers *AgentCore*  
3. **Agent Processing:** 8 agents analyze documents in sequence  
4. **Policy Generation:** HTML underwriting summary → Word policy  
5. **Delivery:** User downloads policy from frontend  

**Total Processing Time:** ~2–3 minutes  


---

## Performance & Security
- **Processing:** 2–3 minutes end-to-end  
- **Resource Usage:** Lightweight client-side; cloud-based heavy lifting  
- **Security:** Encrypted S3 storage, session isolation, IAM-based access  

---

## Future Enhancements
- Multi-language voice support  
- External data integrations  
- Real-time premium calculation  
- Mobile and customer portal extensions  

---
