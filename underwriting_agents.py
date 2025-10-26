import contextlib
import io
import sys
import json
import re
import os
import PyPDF2
import zipfile
from datetime import datetime
from strands import Agent, tool
from strands.models import BedrockModel
from typing import Dict, List, Any
import traceback
import time
import boto3
from dotenv import load_dotenv
from botocore.exceptions import NoCredentialsError, ClientError
from policy_generator import generate_health_insurance_policy

load_dotenv()

from config import (
    UNDERWRITING_GUIDELINES, REQUIRED_DOCUMENTS, RISK_SCORING_RULES, 
    BUSINESS_RULES, LOCAL_CONFIG, AGENT_WORKFLOW_SEQUENCE, LIFESTYLE_RISK_FACTORS
)

UPLOAD_FOLDER = LOCAL_CONFIG['UPLOAD_FOLDER']

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@contextlib.contextmanager
def suppress_output():
    """Context manager to suppress all stdout and stderr output"""
    with open(os.devnull, 'w') as devnull:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        try:
            sys.stdout = devnull
            sys.stderr = devnull
            yield
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

def validate_aws_credentials():
    """Validate AWS credentials including session tokens"""
    try:
        session = boto3.Session()
        sts_client = session.client('sts')
        identity = sts_client.get_caller_identity()
        print(f"[INFO] AWS credentials validated for account: {identity.get('Account', 'Unknown')}")
        bedrock_client = session.client('bedrock-runtime')
        print("[INFO] Bedrock client created successfully")
        return True, session
    except Exception as e:
        print(f"[ERROR] AWS credential validation failed: {e}")
        return False, None

def initialize_nova_pro():
    """Initialize Nova Pro with proper credential handling"""
    try:
        is_valid, session = validate_aws_credentials()
        
        if not is_valid:
            print("[ERROR] Cannot initialize Nova Pro - invalid credentials")
            return None
            
        region = os.getenv('AWS_REGION', 'us-east-1')
        
        # Initialize BedrockModel with explicit credentials
        try:
            
            nova_pro = BedrockModel(
                model_id="amazon.nova-pro-v1:0",
                region_name=region
            )
            
            # Test with a simple call
            test_agent = Agent(
                model=nova_pro,
                system_prompt="You are a test agent. Respond briefly with 'Test successful'."
            )
            
            # Quick test call
            with suppress_output():
                test_result = test_agent("Say test successful")
                
            if test_result and len(str(test_result)) > 5:
                print("[INFO] Nova Pro model initialized and tested successfully")
                return nova_pro
            else:
                print("[WARNING] Nova Pro test call returned empty result")
                return nova_pro  # Return anyway, might work in actual usage
                
        except Exception as e:
            print(f"[ERROR] Nova Pro initialization failed: {e}")
            
           
            try:
                nova_pro = BedrockModel("us.amazon.nova-pro-v1:0")
                print("[INFO] Nova Pro initialized with fallback method")
                return nova_pro
            except Exception as e2:
                print(f"[ERROR] Fallback initialization also failed: {e2}")
                return None
        
    except Exception as e:
        print(f"[ERROR] Nova Pro initialization error: {e}")
        return None

# Initialize Nova Pro model with enhanced error handling
nova_pro = initialize_nova_pro()

if nova_pro is None:
    print("[CRITICAL] Nova Pro model initialization failed - running in fallback mode")
else:
    print("[INFO] Nova Pro model ready for underwriting operations")

def safe_model_call(agent, prompt, max_retries=3):
    """Safely call model with enhanced error handling for session tokens"""
    
    
    is_valid, _ = validate_aws_credentials()
    if not is_valid:
        return "Error: AWS credentials not available or expired. Please refresh your credentials."
    
    for attempt in range(max_retries):
        try:
            with suppress_output():
                result = agent(prompt)
                
           
            if result and len(str(result)) > 10:
                return result
            else:
                print(f"[WARNING] Empty or short result on attempt {attempt + 1}: {result}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                else:
                    return str(result) if result else "No response received from model"
                
        except Exception as e:
            error_msg = str(e)
            print(f"[WARNING] Model call attempt {attempt + 1} failed: {error_msg}")
            
            # Handle specific error types
            if any(keyword in error_msg.lower() for keyword in ['credentials', 'unauthorized', 'token', 'expired']):
                return f"Authentication Error: Your AWS session may have expired. Please refresh your credentials. Details: {error_msg}"
            elif "throttling" in error_msg.lower() or "rate" in error_msg.lower():
                wait_time = 5 * (attempt + 1)
                print(f"[INFO] Rate limiting detected, waiting {wait_time} seconds...")
                time.sleep(wait_time)
                continue
            elif "not found" in error_msg.lower() or "does not exist" in error_msg.lower():
                return f"Model Error: Nova Pro model may not be available in your region. Details: {error_msg}"
                
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            else:
                return f"Model call failed after {max_retries} attempts. Final error: {error_msg}"
    
    return "All retry attempts exhausted - please check your AWS configuration"


class UnderwritingContext: 
    def __init__(self):
        self.agent_data = {}
        self.session_id = None
        self.processed_agents = set()
        self.processing_start_time = None
        self.document_content = ""
        self.s3_client = boto3.client('s3')
        self.s3_bucket = "trianz-aws-hackathon"
    
    def set_session_id(self, session_id: str):
        self.session_id = session_id
        self.processing_start_time = datetime.now()
        print(f"[PROCESS] Context initialized for session: {session_id}")
    
    def add_agent_result(self, agent_name: str, result: str):
        self.agent_data[agent_name] = {
            'analysis': result,
            'timestamp': datetime.now().isoformat(),
            'status': 'completed'
        }
        self.processed_agents.add(agent_name)
        print(f"[INFO] {agent_name.title()} agent completed")
        self.save_agent_status()
    
    def get_agent_result(self, agent_name: str):
        return self.agent_data.get(agent_name, {}).get('analysis', '')
    
    def has_processed(self, agent_name: str):
        return agent_name in self.processed_agents
    
    def get_all_insights(self):
        return {name: data['analysis'] for name, data in self.agent_data.items()}
    
    def save_agent_status(self):
        """Save agent status to S3 with dynamic session folder structure"""
        if not self.session_id:
            return
        
        s3_key = f"{self.session_id}/agent_status.json"
        
        status_data = {
            'session_id': self.session_id,
            'created_at': self.processing_start_time.isoformat() if self.processing_start_time else datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat(),
            'status': 'in_progress',
            'agents': self.agent_data,
            'final_summary': self.agent_data.get('summary_generation', {}).get('analysis', ''),
            'processing_summary': {
                'total_agents': 8,
                'completed_agents': len(self.processed_agents),
                'pending_agents': 8 - len(self.processed_agents),
                'completion_percentage': (len(self.processed_agents) / 8) * 100
            }
        }
        
       
        if 'summary_generation' in self.processed_agents:
            status_data['status'] = 'completed'
        
        try:
            
            self.s3_client.put_object(
                Bucket=self.s3_bucket,
                Key=s3_key,
                Body=json.dumps(status_data, indent=2, ensure_ascii=False),
                ContentType='application/json'
            )
            print(f"[S3] Agent status saved to s3://{self.s3_bucket}/{s3_key}")
            
        except Exception as e:
            print(f"[WARNING] Failed to save agent status to S3: {e}")
    
    def reset(self):
        self.agent_data = {}
        self.processed_agents = set()
        self.session_id = None
        self.processing_start_time = None
        self.document_content = ""

# Global context registry
context_registry = {}

def get_or_create_context(session_id: str) -> UnderwritingContext:
    """Get existing context for session or create new one"""
    if session_id not in context_registry:
        context_registry[session_id] = UnderwritingContext()
        context_registry[session_id].set_session_id(session_id)
    return context_registry[session_id]

def reset_context_for_session(session_id: str) -> UnderwritingContext:
    """Reset context for a specific session"""
    context_registry[session_id] = UnderwritingContext()
    context_registry[session_id].set_session_id(session_id)
    return context_registry[session_id]

class DocumentProcessor:
    """Handles document extraction and analysis"""
    
    def __init__(self):
        self.upload_folder = UPLOAD_FOLDER
        
    def extract_zip_to_session(self, zip_path: str, session_id: str):
        """Extract zip file to session-specific folder"""
        session_upload_path = os.path.join(self.upload_folder, session_id)
        os.makedirs(session_upload_path, exist_ok=True)
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(session_upload_path)
            
            os.remove(zip_path)
            
            return self.get_extracted_pdfs(session_id)
        except Exception as e:
            return {"error": f"Zip extraction failed: {str(e)}"}
    
    def get_extracted_pdfs(self, session_id: str):
        """Get all PDF files from extracted session folder"""
        session_upload_path = os.path.join(self.upload_folder, session_id)
        
        if not os.path.exists(session_upload_path):
            return {"error": "Session folder not found"}
        
        pdf_files = []
        for root, dirs, files in os.walk(session_upload_path):
            for file in files:
                if file.lower().endswith('.pdf'):
                    pdf_files.append({
                        'filename': file,
                        'path': os.path.join(root, file),
                        'relative_path': os.path.relpath(os.path.join(root, file), session_upload_path)
                    })
        
        return {"pdf_files": pdf_files, "total_count": len(pdf_files)}
    
    def analyze_all_pdfs(self, session_id: str):
        """Analyze all PDFs in session folder and combine content"""
        pdf_data = self.get_extracted_pdfs(session_id)
        
        if "error" in pdf_data:
            return pdf_data
        
        combined_content = ""
        document_summaries = []
        
        for pdf_info in pdf_data["pdf_files"]:
            analysis = self.analyze_pdf(pdf_info['path'])
            document_summaries.append({
                'filename': pdf_info['filename'],
                'pages': analysis.get('total_pages', 0),
                'content_length': analysis.get('text_length', 0)
            })
            combined_content += f"\n\n=== DOCUMENT: {pdf_info['filename']} ===\n"
            combined_content += analysis.get('full_text', '')
        
        return {
            "combined_content": combined_content,
            "document_summaries": document_summaries,
            "total_documents": len(pdf_data["pdf_files"]),
            "total_content_length": len(combined_content)
        }
    
    def analyze_pdf(self, pdf_path: str):
        """Analyze individual PDF file with safe encoding handling"""
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                total_pages = len(pdf_reader.pages)
                
                full_text = ""
                
                for i, page in enumerate(pdf_reader.pages):
                    try:
                        page_text = page.extract_text()
                        if page_text:
                            full_text += f"\n--- PAGE {i+1} ---\n{page_text}"
                    except (UnicodeError, UnicodeDecodeError, UnicodeEncodeError) as e:
                        print(f"[WARNING] Encoding issue on page {i+1}: {e}")
                        full_text += f"\n--- PAGE {i+1} ---\nContent extraction failed due to encoding issues"
                    except Exception as e:
                        print(f"[WARNING] Error extracting page {i+1}: {e}")
                        full_text += f"\n--- PAGE {i+1} ---\nPage extraction error"
                
                return {
                    'total_pages': total_pages,
                    'full_text': full_text,
                    'text_length': len(full_text),
                    'is_valid': len(full_text) > 100,
                    'extraction_timestamp': datetime.now().isoformat()
                }
        except Exception as e:
            print(f"[ERROR] PDF analysis failed for {pdf_path}: {e}")
            return {
                'error': f"PDF analysis failed: {str(e)}",
                'is_valid': False,
                'total_pages': 0,
                'text_length': 0
            }

document_processor = DocumentProcessor()

def extract_session_id(input_data: str): #hshhshd
    """Extract session ID from various input formats"""
    
    if not input_data or not isinstance(input_data, str):
        return None
    
    # Direct check for new session format first (highest priority)
    session_match = re.search(r'session_[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}_[a-f0-9]{8}', input_data)
    if session_match:
        return session_match.group(0)
    
    # Fallback patterns for other formats
    patterns = [
        r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})',  # UUID format
        r'"session_id"\s*:\s*"([^"]+)"',  # JSON format
        r'session_id\s*[:=]\s*["\']?([a-f0-9\-_]+)["\']?',  # Key-value format
        r'(session_[a-f0-9\-_]+)',  # Any session_ prefixed ID
        r'([a-f0-9\-_]{8,})'  # Any long alphanumeric string
    ]
    
    for pattern in patterns:
        match = re.search(pattern, input_data, re.IGNORECASE)
        if match:
            return match.group(1)
    
    return None

def log_agent_status(agent_name: str, status: str, details=None):
    """Log status updates for agents"""
    print(f"[AGENT] {agent_name.upper()}: {status}")
    if details:
        print(f"        {details}")

def create_agents():
    """Create all agents with null check"""
    if nova_pro is None:
        print("[WARNING] Nova Pro not available - agents will return error messages")
        return None, None, None, None, None, None, None, None
    
    data_intake_agent = Agent(
        model=nova_pro,
        system_prompt=f"""You are a Senior Data Intake Specialist for Trianz Insurance underwriting operations. Your expertise involves document ingestion, initial processing, and data organization for comprehensive underwriting analysis.

OPERATIONAL GUIDELINES:
Coverage Limits: {UNDERWRITING_GUIDELINES['coverage_limits']['min_coverage']} to {UNDERWRITING_GUIDELINES['coverage_limits']['max_coverage']} USD
Age Range: {UNDERWRITING_GUIDELINES['age_limits']['min_age']} to {UNDERWRITING_GUIDELINES['age_limits']['max_age']} years
Standard Coverage Maximum: {UNDERWRITING_GUIDELINES['coverage_limits']['standard_max']} USD

ANALYSIS APPROACH:
Focus on document intake and initial processing:
1. Document Inventory: Catalog all submitted documents and forms
2. Data Extraction: Extract key applicant information and policy details
3. Initial Classification: Categorize documents by type and relevance
4. Quality Assessment: Evaluate document clarity and completeness
5. Processing Readiness: Determine if submission is ready for specialist review

CURRENCY HANDLING:
Always use USD format in analysis output
Example: Coverage amount 250000 USD, Annual income 85000 USD

OUTPUT REQUIREMENTS:
Provide clear document inventory and initial applicant profile
Identify any immediate processing concerns or data quality issues
Summarize key policy parameters and applicant demographics
Flag any documents that may need special handling or verification
Prepare organized data foundation for downstream specialist analysis

Your intake analysis establishes the foundation for comprehensive underwriting evaluation."""
    )

    document_verification_agent = Agent(
        model=nova_pro,
        system_prompt=f"""You are a Document Verification Specialist for Trianz Insurance with expertise in document authenticity assessment, completeness verification, and regulatory compliance validation.

REQUIRED DOCUMENT STANDARDS:
Application Form: {REQUIRED_DOCUMENTS['application_form']}
Medical Records: Required if {REQUIRED_DOCUMENTS['medical_records']['required_if']}
Driving Records: Required if {REQUIRED_DOCUMENTS['driving_records']['required_if']}
Financial Statements: Required if {REQUIRED_DOCUMENTS['financial_statements']['required_if']}
Identity Verification: {REQUIRED_DOCUMENTS['identity_verification']}

VERIFICATION APPROACH:
Conduct thorough document verification focusing on:
1. Document Completeness: Verify all required documents are present and properly executed
2. Authenticity Assessment: Evaluate document legitimacy and detect potential fraud indicators  
3. Regulatory Compliance: Ensure all regulatory requirements and disclosures are met
4. Signature Verification: Confirm all required signatures and witness requirements
5. Missing Documentation: Identify any gaps that require additional submission

BUSINESS RULE TRIGGERS:
Manual Review Triggers: {BUSINESS_RULES['manual_review_triggers']}
Auto Approval Coverage Maximum: {BUSINESS_RULES['auto_approval_criteria']['coverage_max']} USD

CURRENCY HANDLING:
Always use USD format in analysis output
Example: Coverage verification 150000 USD, Income documentation 92000 USD

OUTPUT REQUIREMENTS:
Provide comprehensive document verification status and completeness assessment
Highlight any authentication concerns or regulatory compliance issues
Identify specific missing documents or information required for processing
Assess overall submission quality and readiness for underwriting review
Recommend specific actions needed to complete documentation requirements

Your verification ensures all submissions meet regulatory standards and company requirements."""
    )

    medical_risk_assessment_agent = Agent(
        model=nova_pro,
        system_prompt=f"""You are a Senior Medical Risk Assessment Specialist for Trianz Insurance with extensive experience in medical underwriting, mortality risk evaluation, and health condition analysis.

MEDICAL RISK PARAMETERS:
Health Risk Indicators: {RISK_SCORING_RULES['health_risk_indicators']}
Medical Requirements: {UNDERWRITING_GUIDELINES['medical_requirements']}
Age-Based Medical Thresholds: Full exam required at age {UNDERWRITING_GUIDELINES['age_limits']['senior_threshold']}

ASSESSMENT APPROACH:
Analyze medical information focusing on:
1. Current Health Status: Active medical conditions, treatment status, and prognosis
2. Medical History: Significant past conditions, surgeries, and hospitalizations
3. Medication Analysis: Current prescriptions, dosages, and treatment compliance
4. Lifestyle Health Factors: Smoking, alcohol use, exercise, and diet patterns
5. Mortality Risk Evaluation: Conditions impacting life expectancy and insurability

MORTALITY FACTOR WEIGHTING:
Health Weight in Overall Risk: {RISK_SCORING_RULES['mortality_factors']['health_weight']}
Age Weight in Overall Risk: {RISK_SCORING_RULES['mortality_factors']['age_weight']}

CURRENCY HANDLING:
Always use USD format in analysis output
Example: Medical expenses 8500 USD annually, Prescription costs 2400 USD

OUTPUT REQUIREMENTS:
Provide comprehensive medical risk assessment with clear risk classification
Explain medical findings and their impact on mortality and insurability
Identify any conditions requiring additional medical information or specialist consultation
Assess treatment compliance and healthcare engagement patterns
Recommend appropriate medical risk rating and any coverage modifications needed

Your medical analysis determines the health-based risk classification for coverage decisions."""
    )

    financial_agent = Agent(
        model=nova_pro,
        system_prompt=f"""You are a Financial Underwriting Specialist for trianz Insurance specializing in financial capacity analysis, coverage appropriateness assessment, and anti-selection risk evaluation.

FINANCIAL UNDERWRITING PARAMETERS:
Income Multiplier Guideline: {UNDERWRITING_GUIDELINES['financial_ratios']['income_multiplier']}x annual income
Maximum Debt-to-Income Ratio: {UNDERWRITING_GUIDELINES['financial_ratios']['debt_to_income_max']}
Minimum Net Worth Requirement: {UNDERWRITING_GUIDELINES['financial_ratios']['net_worth_min']} USD
Financial Weight in Risk Scoring: {RISK_SCORING_RULES['mortality_factors']['financial_weight']}

ANALYSIS APPROACH:
Evaluate financial information focusing on:
1. Income Analysis: Stability, sources, and verification of reported income
2. Asset Assessment: Liquid assets, investments, real estate, and total net worth
3. Debt Evaluation: Outstanding obligations and debt service requirements
4. Coverage Appropriateness: Relationship between requested coverage and financial capacity
5. Anti-Selection Indicators: Excessive coverage requests or unusual financial circumstances

BUSINESS RULE COMPLIANCE:
Auto Approval Financial Score Minimum: {BUSINESS_RULES['auto_approval_criteria']['financial_score_min']}
Coverage Limits: {UNDERWRITING_GUIDELINES['coverage_limits']['min_coverage']} to {UNDERWRITING_GUIDELINES['coverage_limits']['max_coverage']} USD

CURRENCY HANDLING:
Always use USD format in analysis output
Example: Annual income 125000 USD, Requested coverage 500000 USD, Net worth 450000 USD

OUTPUT REQUIREMENTS:
Provide comprehensive financial capacity assessment and coverage appropriateness analysis
Explain the relationship between income, assets, and requested coverage amount
Identify any financial red flags or anti-selection concerns
Assess premium affordability and long-term financial sustainability
Recommend coverage limits and any additional financial requirements needed

Your financial analysis ensures coverage amounts are appropriate and financially justified."""
    )

    driving_agent = Agent(
        model=nova_pro,
        system_prompt=f"""You are a Motor Vehicle Records Specialist for Trianz Insurance with expertise in driving history evaluation, traffic violation assessment, and transportation-related mortality risk analysis.

DRIVING ASSESSMENT PARAMETERS:
Required Coverage Threshold: {REQUIRED_DOCUMENTS['driving_records']['required_if']}
Lookback Period: {REQUIRED_DOCUMENTS['driving_records']['lookback_years']} years
Poor Driving Risk Factor: {RISK_SCORING_RULES['lifestyle_risk_factors']['poor_driving']}

EVALUATION APPROACH:
Analyze driving records focusing on:
1. Violation History: Traffic citations, frequency, and severity assessment
2. Accident Analysis: At-fault incidents, claims history, and injury patterns
3. License Status: Current validity, restrictions, suspensions, or revocations
4. High-Risk Behavior: Reckless driving, speed violations, and dangerous patterns
5. Substance-Related Violations: DUI/DWI history and substance abuse indicators

LIFESTYLE RISK INTEGRATION:
Lifestyle Weight in Overall Risk: {RISK_SCORING_RULES['mortality_factors']['lifestyle_weight']}
Criminal Record Impact: {LIFESTYLE_RISK_FACTORS['criminal_record']}

CURRENCY HANDLING:
Always use USD format in analysis output
Example: Accident damages 15000 USD, Traffic fines 850 USD, Legal costs 3200 USD

OUTPUT REQUIREMENTS:
Provide comprehensive driving risk assessment with clear risk level classification
Explain how driving violations and patterns impact overall mortality risk
Identify concerning behaviors or patterns that indicate increased risk
Assess overall driving record quality and insurance implications
Recommend appropriate risk adjustments or coverage modifications based on driving history

Your driving analysis identifies transportation-related risks that may impact life insurance mortality assumptions."""
    )

    compliance_agent = Agent(
        model=nova_pro,
        system_prompt=f"""You are a Regulatory Compliance Specialist for Trianz Insurance ensuring all underwriting activities meet federal, state, and company regulatory requirements.

COMPLIANCE FRAMEWORK:
Required Documents: {REQUIRED_DOCUMENTS}
Business Rules: {BUSINESS_RULES}
Decline Criteria: {BUSINESS_RULES['decline_criteria']}

COMPLIANCE VERIFICATION APPROACH:
Review all aspects for regulatory compliance focusing on:
1. Documentation Compliance: Required forms, signatures, disclosures, and witness requirements
2. Regulatory Requirements: Federal and state insurance law compliance verification
3. Privacy Compliance: HIPAA, consumer privacy rights, and information handling requirements
4. Anti-Fraud Measures: Identity verification, application accuracy, and fraud prevention
5. Company Policy Adherence: Internal underwriting guidelines and procedure compliance

BUSINESS RULE VALIDATION:
Auto Approval Criteria: Age {BUSINESS_RULES['auto_approval_criteria']['age_range']}, Coverage max {BUSINESS_RULES['auto_approval_criteria']['coverage_max']} USD
Manual Review Triggers: {BUSINESS_RULES['manual_review_triggers']}

CURRENCY HANDLING:
Always use USD format in analysis output
Example: Compliance review cost 1800 USD, Regulatory requirements 2500 USD

OUTPUT REQUIREMENTS:
Provide comprehensive compliance status assessment with specific requirement verification
Identify any missing documentation, signatures, or regulatory requirements
Explain compliance implications and potential consequences of any deficiencies
Detail specific remediation steps required to achieve full compliance
Ensure thorough documentation of compliance review and approval recommendations

Your compliance analysis ensures all underwriting activities meet legal standards and regulatory requirements."""
    )

    lifestyle_behavioral_agent = Agent(
        model=nova_pro,
        system_prompt=f"""You are a Lifestyle and Behavioral Risk Specialist for Trianz Insurance with expertise in behavioral pattern analysis, lifestyle risk assessment, and psychosocial factor evaluation.

LIFESTYLE RISK ASSESSMENT PARAMETERS:
Lifestyle Risk Factors: {LIFESTYLE_RISK_FACTORS}
Lifestyle Weight in Overall Risk: {RISK_SCORING_RULES['mortality_factors']['lifestyle_weight']}
Behavioral Risk Categories: Substance use, mental health, occupational hazards, financial behavior, family factors

ASSESSMENT APPROACH:
Analyze lifestyle and behavioral factors focusing on:
1. Substance Use Assessment: Current and historical alcohol, tobacco, and drug use patterns
2. Mental Health Evaluation: Depression, anxiety, stress-related conditions, and treatment history
3. Occupational Risk Analysis: Job-related hazards, stress levels, and safety concerns
4. Social Risk Factors: Family history, relationship stability, and support systems
5. Financial Behavior Patterns: Credit history, bankruptcy, insurance claims, and financial responsibility

RISK FACTOR ANALYSIS:
High-Impact Factors: Suicide attempt history ({LIFESTYLE_RISK_FACTORS['suicide_attempt_history']}), Insurance fraud ({LIFESTYLE_RISK_FACTORS['insurance_fraud_history']})
Moderate-Impact Factors: Smoking ({LIFESTYLE_RISK_FACTORS['smoking_current']}), Depression history ({LIFESTYLE_RISK_FACTORS['depression_history']})

CURRENCY HANDLING:
Always use USD format in analysis output
Example: Behavioral assessment cost 1200 USD, Treatment expenses 4500 USD annually

OUTPUT REQUIREMENTS:
Provide comprehensive lifestyle and behavioral risk assessment with detailed factor analysis
Explain how identified behavioral patterns impact mortality risk and insurability
Identify any high-risk behaviors or concerning patterns requiring additional investigation
Assess overall lifestyle risk profile and recommend appropriate risk classification adjustments
Document specific behavioral factors and their quantified impact on underwriting decision

Your behavioral analysis provides critical insights into lifestyle-related mortality risks for accurate risk assessment."""
    )

    summary_generation_agent = Agent(
        model=nova_pro,
        system_prompt=f"""You are the Chief Underwriting Officer for Trianz Insurance responsible for generating comprehensive underwriting summaries in professional TABLE-BASED HTML format for executive review and decision-making, format for generating the summary will be same you will follow a standard procedure and format of generating the summary so everytime you generate the summary format and structure must be same only make sure there is no markdown ```html don't write ```html markdown.

UNDERWRITING DECISION FRAMEWORK:
Risk Categories: {UNDERWRITING_GUIDELINES['risk_categories']}
Approval Thresholds: {RISK_SCORING_RULES['approval_thresholds']}
Coverage Limits: {UNDERWRITING_GUIDELINES['coverage_limits']['min_coverage']} to {UNDERWRITING_GUIDELINES['coverage_limits']['max_coverage']} USD

MANDATORY TABLE-BASED HTML FORMAT:
Create a professional structured table-based underwriting summary using HTML tables with the following sections:

1. APPLICATION SUMMARY TABLE - Key applicant and policy details
2. DOCUMENT VERIFICATION TABLE - Document status and completeness
3. RISK ASSESSMENT SUMMARY TABLE - All risk factors and scores
4. MEDICAL ASSESSMENT TABLE - Health conditions and risk ratings
5. FINANCIAL ANALYSIS TABLE - Income, assets, coverage appropriateness
6. DRIVING RECORD TABLE - Violations, accidents, risk classification
7. COMPLIANCE STATUS TABLE - Regulatory requirements and status
8. LIFESTYLE RISK TABLE - Behavioral factors and risk impact
9. UNDERWRITING DECISION TABLE - Final recommendation and conditions

BUSINESS RULES APPLICATION:
Auto Approval Criteria: {BUSINESS_RULES['auto_approval_criteria']}
Manual Review Triggers: {BUSINESS_RULES['manual_review_triggers']}
Decline Criteria: {BUSINESS_RULES['decline_criteria']}

CURRENCY HANDLING:
Always use USD format throughout summary
Example: Coverage amount 300000 USD, Annual premium 2800 USD, Income verification 95000 USD

CRITICAL HTML TABLE REQUIREMENTS:
Use <table>, <thead>, <tbody>, <tr>, <th>, <td> elements exclusively
Include proper table headers with <th> elements
Use CSS-friendly class names (underwriting-table, summary-section, etc.)
Each section must be a separate table with clear headers
Include all key values, scores, and recommendations in structured rows
Professional executive-level table formatting suitable for reports
NO paragraphs or narrative text - ONLY structured table data
Clean, valid HTML syntax suitable for web display and printing

TABLE STRUCTURE EXAMPLE:
<table class="underwriting-table">
<thead>
<tr><th>Parameter</th><th>Value</th><th>Status</th><th>Notes</th></tr>
</thead>
<tbody>
<tr><td>Coverage Amount</td><td>$300,000 USD</td><td>Appropriate</td><td>Within guidelines</td></tr>
</tbody>
</table>

Your HTML table summary serves as the official structured underwriting decision document for executive review and policy issuance. Do not include markdown formatting in the output."""
    )
    
    return (data_intake_agent, document_verification_agent, medical_risk_assessment_agent, 
            financial_agent, driving_agent, compliance_agent, lifestyle_behavioral_agent, 
            summary_generation_agent)

# Create agents
try:
    (data_intake_agent, document_verification_agent, medical_risk_assessment_agent, 
     financial_agent, driving_agent, compliance_agent, lifestyle_behavioral_agent, 
     summary_generation_agent) = create_agents() or (None,) * 8
except Exception as e:
    print(f"[ERROR] Failed to create agents: {e}")
    (data_intake_agent, document_verification_agent, medical_risk_assessment_agent, 
     financial_agent, driving_agent, compliance_agent, lifestyle_behavioral_agent, 
     summary_generation_agent) = (None,) * 8

# Tool Functions

@tool
def data_intake_tool(session_data: str) -> str:
    """Process document intake and initial data extraction"""
    session_id = extract_session_id(session_data)
    if not session_id:
        return "Session ID not found"
    
    context = get_or_create_context(session_id)
    
    if context.has_processed('data_intake'):
        return "Data intake already completed"
    
    try:
        log_agent_status('data_intake', 'Starting document intake and processing')
        
        document_analysis = document_processor.analyze_all_pdfs(session_id)
        
        if "error" in document_analysis:
            return f"Document analysis failed: {document_analysis['error']}"
        
        context.document_content = document_analysis["combined_content"]
        
        if data_intake_agent is None:
            intake_analysis = "Error: Data intake agent not available due to AWS credential issues. Please check your AWS configuration."
        else:
            intake_prompt = f"""Please conduct comprehensive document intake and initial processing for this Insurance underwriting case:

DOCUMENT INVENTORY:
Total Documents Submitted: {document_analysis["total_documents"]}
Combined Content Length: {document_analysis["total_content_length"]} characters

DOCUMENT CONTENTS:
{document_analysis["combined_content"]}

DOCUMENT SUMMARY BY FILE:
{json.dumps(document_analysis["document_summaries"], indent=2)}

Please provide comprehensive data intake analysis focusing on:
- Complete document inventory and classification
- Initial applicant demographic and policy information extraction
- Key policy parameters identification (coverage amount, term, beneficiaries)
- Document quality assessment and processing readiness
- Any immediate concerns or data quality issues requiring attention
- Preliminary assessment of submission completeness for underwriting review

Your analysis establishes the foundation for all subsequent specialist underwriting evaluations."""
            
            intake_analysis = safe_model_call(data_intake_agent, intake_prompt)
        
        context.add_agent_result('data_intake', str(intake_analysis))
        
        log_agent_status('data_intake', 'Document intake completed', 
                        f"Processed {document_analysis['total_documents']} documents")
        print(f"\n[AGENT_RESULT] DATA_INTAKE:\n{intake_analysis}\n" + "="*80 + "\n")
        return str(intake_analysis)
        
    except Exception as e:
        error_msg = f"Data intake error: {str(e)}"
        log_agent_status('data_intake', 'Processing failed', str(e))
        return error_msg

@tool
def document_verification_tool(session_data: str) -> str:
    """Verify document completeness and authenticity"""
    session_id = extract_session_id(session_data)
    if not session_id:
        return "Session ID not found"
    
    context = get_or_create_context(session_id)
    
    if context.has_processed('document_verification'):
        return "Document verification already completed"
    
    try:
        log_agent_status('document_verification', 'Starting document verification and compliance check')
        
        if not context.document_content:
            document_analysis = document_processor.analyze_all_pdfs(session_id)
            if "error" in document_analysis:
                return f"Document analysis failed: {document_analysis['error']}"
            context.document_content = document_analysis["combined_content"]
        
        # Get data intake results for context
        intake_results = context.get_agent_result('data_intake')
        
        if document_verification_agent is None:
            verification_analysis = "Error: Document verification agent not available due to AWS credential issues. Please check your AWS configuration."
        else:
            verification_prompt = f"""Please conduct thorough document verification for this Insurance underwriting submission:

INITIAL DATA INTAKE RESULTS:
{intake_results}

COMPLETE DOCUMENT CONTENT FOR VERIFICATION:
{context.document_content}

Please provide comprehensive document verification analysis focusing on:
- Document completeness verification against  requirements
- Authentication assessment and fraud indicator detection
- Regulatory compliance verification (signatures, disclosures, witness requirements)
- Missing documentation identification with specific requirements
- Document quality and acceptability assessment
- Identity verification and applicant authentication status
- Overall submission readiness for underwriting review

Your verification ensures all regulatory and company documentation standards are met before proceeding with risk assessment."""
            
            verification_analysis = safe_model_call(document_verification_agent, verification_prompt)
        
        context.add_agent_result('document_verification', str(verification_analysis))
        
        log_agent_status('document_verification', 'Document verification completed')
        print(f"\n[AGENT_RESULT] DOCUMENT_VERIFICATION:\n{verification_analysis}\n" + "="*80 + "\n")
        return str(verification_analysis)
        
    except Exception as e:
        error_msg = f"Document verification error: {str(e)}"
        log_agent_status('document_verification', 'Verification failed', str(e))
        return error_msg

@tool
def medical_risk_assessment_tool(session_data: str) -> str:
    """Analyze medical records and assess health-related risks"""
    session_id = extract_session_id(session_data)
    if not session_id:
        return "Session ID not found"
    
    context = get_or_create_context(session_id)
    
    if context.has_processed('medical_risk_assessment'):
        return "Medical risk assessment already completed"
    
    try:
        log_agent_status('medical_risk_assessment', 'Starting comprehensive medical risk analysis')
        
        if not context.document_content:
            document_analysis = document_processor.analyze_all_pdfs(session_id)
            if "error" in document_analysis:
                return f"Document analysis failed: {document_analysis['error']}"
            context.document_content = document_analysis["combined_content"]
        
        # Get previous agent results for context
        previous_results = {
            'data_intake': context.get_agent_result('data_intake'),
            'document_verification': context.get_agent_result('document_verification')
        }
        
        if medical_risk_assessment_agent is None:
            medical_analysis = "Error: Medical risk assessment agent not available due to AWS credential issues. Please check your AWS configuration."
        else:
            medical_prompt = f"""Please conduct comprehensive medical risk assessment for this  Insurance underwriting case:

PREVIOUS ANALYSIS CONTEXT:
Data Intake Results: {previous_results['data_intake']}
Document Verification Status: {previous_results['document_verification']}

MEDICAL INFORMATION FOR ANALYSIS:
{context.document_content}

Please provide detailed medical risk assessment focusing on:
- Current health status evaluation and condition severity assessment
- Medical history analysis including surgeries, hospitalizations, and chronic conditions
- Prescription medication review including dosages, compliance, and treatment effectiveness
- Lifestyle health factors including smoking, alcohol use, diet, and exercise patterns
- Family medical history assessment and hereditary risk factors
- Mortality risk evaluation and life expectancy impact analysis
- Medical risk classification recommendation with supporting rationale

Your medical analysis determines the health-related risk classification for this underwriting decision."""
            
            medical_analysis = safe_model_call(medical_risk_assessment_agent, medical_prompt)
        
        context.add_agent_result('medical_risk_assessment', str(medical_analysis))
        
        log_agent_status('medical_risk_assessment', 'Medical risk assessment completed')
        print(f"\n[AGENT_RESULT] MEDICAL_RISK_ASSESSMENT:\n{medical_analysis}\n" + "="*80 + "\n")
        return str(medical_analysis)
        
    except Exception as e:
        error_msg = f"Medical risk assessment error: {str(e)}"
        log_agent_status('medical_risk_assessment', 'Analysis failed', str(e))
        return error_msg

@tool
def financial_analysis_tool(session_data: str) -> str:
    """Analyze financial capacity and coverage appropriateness"""
    session_id = extract_session_id(session_data)
    if not session_id:
        return "Session ID not found"
    
    context = get_or_create_context(session_id)
    
    if context.has_processed('financial'):
        return "Financial analysis already completed"
    
    try:
        log_agent_status('financial', 'Starting financial capacity and appropriateness analysis')
        
        if not context.document_content:
            document_analysis = document_processor.analyze_all_pdfs(session_id)
            if "error" in document_analysis:
                return f"Document analysis failed: {document_analysis['error']}"
            context.document_content = document_analysis["combined_content"]
        
        # Get previous agent results for context
        previous_results = {
            'data_intake': context.get_agent_result('data_intake'),
            'document_verification': context.get_agent_result('document_verification'),
            'medical_risk_assessment': context.get_agent_result('medical_risk_assessment')
        }
        
        if financial_agent is None:
            financial_analysis = "Error: Financial analysis agent not available due to AWS credential issues. Please check your AWS configuration."
        else:
            financial_prompt = f"""Please conduct comprehensive financial analysis for this Insurance underwriting case:

PREVIOUS ANALYSIS CONTEXT:
Data Intake Results: {previous_results['data_intake']}
Document Verification Status: {previous_results['document_verification']}
Medical Risk Assessment: {previous_results['medical_risk_assessment']}

FINANCIAL INFORMATION FOR ANALYSIS:
{context.document_content}

Please provide detailed financial analysis focusing on:
- Income analysis including stability, sources, and verification adequacy
- Asset assessment including liquid assets, investments, real estate, and total net worth
- Debt evaluation including outstanding obligations and debt service capacity
- Coverage appropriateness analysis relative to income, assets, and financial capacity
- Premium affordability assessment and long-term sustainability evaluation
- Anti-selection risk indicators including excessive coverage or unusual circumstances
- Financial risk classification with supporting rationale and recommendations

Your financial analysis ensures requested coverage is appropriate and financially justified."""
            
            financial_analysis = safe_model_call(financial_agent, financial_prompt)
        
        context.add_agent_result('financial', str(financial_analysis))
        
        log_agent_status('financial', 'Financial analysis completed')
        print(f"\n[AGENT_RESULT] FINANCIAL_ANALYSIS:\n{financial_analysis}\n" + "="*80 + "\n")
        return str(financial_analysis)
        
    except Exception as e:
        error_msg = f"Financial analysis error: {str(e)}"
        log_agent_status('financial', 'Analysis failed', str(e))
        return error_msg

@tool
def driving_analysis_tool(session_data: str) -> str:
    """Analyze driving records and motor vehicle history"""
    session_id = extract_session_id(session_data)
    if not session_id:
        return "Session ID not found"
    
    context = get_or_create_context(session_id)
    
    if context.has_processed('driving'):
        return "Driving analysis already completed"
    
    try:
        log_agent_status('driving', 'Starting driving record and motor vehicle analysis')
        
        if not context.document_content:
            document_analysis = document_processor.analyze_all_pdfs(session_id)
            if "error" in document_analysis:
                return f"Document analysis failed: {document_analysis['error']}"
            context.document_content = document_analysis["combined_content"]
        
        # Get previous agent results for context
        previous_results = {
            'data_intake': context.get_agent_result('data_intake'),
            'document_verification': context.get_agent_result('document_verification'),
            'medical_risk_assessment': context.get_agent_result('medical_risk_assessment'),
            'financial': context.get_agent_result('financial')
        }
        
        if driving_agent is None:
            driving_analysis = "Error: Driving analysis agent not available due to AWS credential issues. Please check your AWS configuration."
        else:
            driving_prompt = f"""Please conduct comprehensive driving record analysis for this Insurance underwriting case:

PREVIOUS ANALYSIS CONTEXT:
Data Intake Results: {previous_results['data_intake']}
Document Verification Status: {previous_results['document_verification']}
Medical Risk Assessment: {previous_results['medical_risk_assessment']}
Financial Analysis: {previous_results['financial']}

DRIVING AND MOTOR VEHICLE INFORMATION FOR ANALYSIS:
{context.document_content}

Please provide detailed driving record analysis focusing on:
- Traffic violation history including frequency, severity, and patterns
- Accident record analysis including at-fault incidents and claims history
- License status verification including validity, restrictions, and suspensions
- High-risk driving behavior identification and pattern analysis
- DUI/DWI history assessment and substance abuse implications
- Overall driving risk evaluation and mortality impact assessment
- Driving risk classification with supporting rationale and recommendations

Your driving analysis identifies transportation-related risks impacting life insurance mortality assumptions."""
            
            driving_analysis = safe_model_call(driving_agent, driving_prompt)
        
        context.add_agent_result('driving', str(driving_analysis))
        
        log_agent_status('driving', 'Driving record analysis completed')
        print(f"\n[AGENT_RESULT] DRIVING_ANALYSIS:\n{driving_analysis}\n" + "="*80 + "\n")
        return str(driving_analysis)
        
    except Exception as e:
        error_msg = f"Driving analysis error: {str(e)}"
        log_agent_status('driving', 'Analysis failed', str(e))
        return error_msg

@tool
def compliance_analysis_tool(session_data: str) -> str:
    """Verify regulatory compliance and documentation requirements"""
    session_id = extract_session_id(session_data)
    if not session_id:
        return "Session ID not found"
    
    context = get_or_create_context(session_id)
    
    if context.has_processed('compliance'):
        return "Compliance analysis already completed"
    
    try:
        log_agent_status('compliance', 'Starting regulatory compliance verification')
        
        if not context.document_content:
            document_analysis = document_processor.analyze_all_pdfs(session_id)
            if "error" in document_analysis:
                return f"Document analysis failed: {document_analysis['error']}"
            context.document_content = document_analysis["combined_content"]
        
        # Get all previous agent results for comprehensive compliance review
        all_previous_results = {
            'data_intake': context.get_agent_result('data_intake'),
            'document_verification': context.get_agent_result('document_verification'),
            'medical_risk_assessment': context.get_agent_result('medical_risk_assessment'),
            'financial': context.get_agent_result('financial'), 
            'driving': context.get_agent_result('driving')
        }
        
        if compliance_agent is None:
            compliance_analysis = "Error: Compliance analysis agent not available due to AWS credential issues. Please check your AWS configuration."
        else:
            compliance_prompt = f"""Please conduct comprehensive regulatory compliance verification for this Insurance underwriting case:

ALL PREVIOUS SPECIALIST ANALYSIS:
{json.dumps(all_previous_results, indent=2)}

ORIGINAL DOCUMENTATION FOR COMPLIANCE REVIEW:
{context.document_content}

Please provide detailed compliance analysis focusing on:
- Documentation completeness verification against all regulatory requirements
- Federal and state insurance law compliance assessment
- Privacy and disclosure requirement verification including HIPAA compliance
- Anti-fraud measures including identity verification and application accuracy
- Company policy adherence verification and procedure compliance
- Missing documentation identification with specific remediation requirements
- Overall compliance status assessment and approval readiness evaluation

Your compliance analysis ensures all legal and regulatory standards are met before policy issuance."""
            
            compliance_analysis = safe_model_call(compliance_agent, compliance_prompt)
        
        context.add_agent_result('compliance', str(compliance_analysis))
        
        log_agent_status('compliance', 'Compliance verification completed')
        print(f"\n[AGENT_RESULT] COMPLIANCE_ANALYSIS:\n{compliance_analysis}\n" + "="*80 + "\n")
        return str(compliance_analysis)
        
    except Exception as e:
        error_msg = f"Compliance analysis error: {str(e)}"
        log_agent_status('compliance', 'Analysis failed', str(e))
        return error_msg

@tool
def lifestyle_behavioral_analysis_tool(session_data: str) -> str:
    """Analyze lifestyle and behavioral risk factors"""
    session_id = extract_session_id(session_data)
    if not session_id:
        return "Session ID not found"
    
    context = get_or_create_context(session_id)
    
    if context.has_processed('lifestyle_behavioral'):
        return "Lifestyle behavioral analysis already completed"
    
    try:
        log_agent_status('lifestyle_behavioral', 'Starting lifestyle and behavioral risk assessment')
        
        if not context.document_content:
            document_analysis = document_processor.analyze_all_pdfs(session_id)
            if "error" in document_analysis:
                return f"Document analysis failed: {document_analysis['error']}"
            context.document_content = document_analysis["combined_content"]
        
        # Get all previous agent results for comprehensive lifestyle assessment
        all_previous_results = {
            'data_intake': context.get_agent_result('data_intake'),
            'document_verification': context.get_agent_result('document_verification'),
            'medical_risk_assessment': context.get_agent_result('medical_risk_assessment'),
            'financial': context.get_agent_result('financial'),
            'driving': context.get_agent_result('driving'),
            'compliance': context.get_agent_result('compliance')
        }
        
        if lifestyle_behavioral_agent is None:
            lifestyle_analysis = "Error: Lifestyle behavioral analysis agent not available due to AWS credential issues. Please check your AWS configuration."
        else:
            lifestyle_prompt = f"""Please conduct comprehensive lifestyle and behavioral risk analysis for this Insurance underwriting case:

ALL PREVIOUS SPECIALIST ANALYSIS:
{json.dumps(all_previous_results, indent=2)}

ORIGINAL DOCUMENTATION FOR LIFESTYLE ASSESSMENT:
{context.document_content}

Please provide detailed lifestyle and behavioral analysis focusing on:
- Substance use assessment including current and historical alcohol, tobacco, and drug use
- Mental health evaluation including depression, anxiety, and stress-related conditions
- Occupational risk analysis including job hazards, stress levels, and safety concerns
- Social risk factor assessment including family history and relationship stability
- Financial behavior pattern evaluation including credit history and responsibility indicators
- High-impact risk factor identification and quantified mortality impact assessment
- Overall lifestyle risk classification with supporting rationale and recommendations

Your behavioral analysis provides critical lifestyle-related mortality risk insights for accurate underwriting."""
            
            lifestyle_analysis = safe_model_call(lifestyle_behavioral_agent, lifestyle_prompt)
        
        context.add_agent_result('lifestyle_behavioral', str(lifestyle_analysis))
        
        log_agent_status('lifestyle_behavioral', 'Lifestyle behavioral analysis completed')
        print(f"\n[AGENT_RESULT] LIFESTYLE_BEHAVIORAL_ANALYSIS:\n{lifestyle_analysis}\n" + "="*80 + "\n")
        return str(lifestyle_analysis)
        
    except Exception as e:
        error_msg = f"Lifestyle behavioral analysis error: {str(e)}"
        log_agent_status('lifestyle_behavioral', 'Analysis failed', str(e))
        return error_msg
@tool
def policy_generation_tool(session_data: str) -> str:
    """Generate health insurance policy document after successful underwriting"""
    session_id = extract_session_id(session_data)
    if not session_id:
        return "Session ID not found"
    
    context = get_or_create_context(session_id)
    
    try:
        log_agent_status('policy_generation', 'Starting policy document generation')
        
        # Check if summary generation is completed
        if not context.has_processed('summary_generation'):
            return "Summary generation must be completed before policy generation"
        
        # Generate policy
        policy_result = generate_health_insurance_policy(session_id)
        
        if policy_result['status'] == 'success':
            context.add_agent_result('policy_generation', json.dumps(policy_result, indent=2))
            log_agent_status('policy_generation', 'Policy document generated successfully', 
                           f"S3: {policy_result.get('s3_location', 'N/A')}")
            return f"Policy generated successfully: {policy_result.get('local_file', 'N/A')}"
        
        elif policy_result['status'] == 'declined':
            context.add_agent_result('policy_generation', 'Underwriting declined - policy not generated')
            log_agent_status('policy_generation', 'Skipped - underwriting declined')
            return "Policy generation skipped: Underwriting declined"
        
        elif policy_result['status'] == 'skipped':
            log_agent_status('policy_generation', 'Skipped - underwriting incomplete')
            return "Policy generation skipped: Underwriting not completed"
        
        else:
            error_msg = policy_result.get('error', 'Unknown error')
            log_agent_status('policy_generation', 'Policy generation failed', error_msg)
            return f"Policy generation failed: {error_msg}"
        
    except Exception as e:
        error_msg = f"Policy generation error: {str(e)}"
        log_agent_status('policy_generation', 'Generation failed', str(e))
        return error_msg
@tool
def summary_generation_tool(session_data: str) -> str:
    """Generate comprehensive underwriting summary with final decision"""
    session_id = extract_session_id(session_data)
    if not session_id:
        return "Session ID not found"
    
    context = get_or_create_context(session_id)
    
    if context.has_processed('summary_generation'):
        return "Summary generation already completed"
    
    try:
        log_agent_status('summary_generation', 'Generating comprehensive underwriting summary')
        
        # Get all specialist agent results
        all_insights = context.get_all_insights()
        
        if len(all_insights) < 7:
            return "Insufficient specialist analyses available for summary generation"
        
        if summary_generation_agent is None:
            # Generate fallback summary when agent is not available
            comprehensive_summary = f"""<div class="underwriting-summary">
<h1>Trianz Insurance Underwriting & Policy Generation </h1>

<div class="session-info">
<h2>Session Information</h2>
<p><strong>Session ID:</strong> {session_id}</p>
<p><strong>Processing Date:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
<p><strong>Status:</strong> Summary Generated (Fallback Mode)</p>
<p><strong>Agents Processed:</strong> {len(all_insights)} of 8</p>
</div>

<div class="agent-results">
<h2>Specialist Analysis Results</h2>"""
            
            for agent_name, analysis in all_insights.items():
                comprehensive_summary += f"""<div class="agent-analysis">
<h3>{agent_name.replace('_', ' ').title()} Analysis</h3>
<div class="analysis-content">
<p>{analysis}</p>
</div>
</div>"""
            
            comprehensive_summary += """</div>

<div class="processing-note">
<h2>Processing Status</h2>
<p>This summary was generated in fallback mode due to AWS credential issues. All specialist analyses were completed but the final AI-generated summary was not available. Please contact technical support if full AI summarization is required.</p>
</div>
</div>"""
        else:
            summary_prompt = f"""Please create a comprehensive underwriting summary in HTML format consolidating all specialist findings:

SESSION INFORMATION:
Session ID: {session_id}
Processing Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Total Specialists Completed: {len(all_insights)}

COMPLETE SPECIALIST ANALYSIS RESULTS:

DATA INTAKE ANALYSIS:
{all_insights.get('data_intake', 'Not available')}

DOCUMENT VERIFICATION ANALYSIS:
{all_insights.get('document_verification', 'Not available')}

MEDICAL RISK ASSESSMENT:
{all_insights.get('medical_risk_assessment', 'Not available')}

FINANCIAL ANALYSIS:
{all_insights.get('financial', 'Not available')}

DRIVING RECORD ANALYSIS:
{all_insights.get('driving', 'Not available')}

COMPLIANCE VERIFICATION:
{all_insights.get('compliance', 'Not available')}

LIFESTYLE BEHAVIORAL ANALYSIS:
{all_insights.get('lifestyle_behavioral', 'Not available')}

Please create a comprehensive executive underwriting summary in HTML format including:

1. EXECUTIVE SUMMARY: Key findings, risk classification, and final underwriting recommendation
2. APPLICANT PROFILE: Essential demographics, occupation, and coverage request details
3. COMPREHENSIVE RISK ASSESSMENT: Integrated analysis of all specialist findings
4. MEDICAL FINDINGS: Critical health-related insights and mortality impact
5. FINANCIAL APPROPRIATENESS: Coverage justification and premium recommendations
6. COMPLIANCE STATUS: Regulatory compliance verification and documentation status
7. LIFESTYLE RISK EVALUATION: Behavioral factors and their impact on risk classification
8. FINAL UNDERWRITING DECISION: Clear recommendation with detailed supporting rationale
9. IMPLEMENTATION REQUIREMENTS: Specific conditions, exclusions, or additional requirements
10. NEXT STEPS: Required actions for case completion and policy issuance

Format as professional HTML suitable for executive review and frontend display."""
            
            comprehensive_summary = safe_model_call(summary_generation_agent, summary_prompt)
        
        context.add_agent_result('summary_generation', str(comprehensive_summary))
        
        processing_time = "Unknown"
        if context.processing_start_time:
            elapsed = datetime.now() - context.processing_start_time
            processing_time = f"{elapsed.seconds} seconds"
        
        log_agent_status('summary_generation', f'Comprehensive summary generated', f'Processing time: {processing_time}')
        try:
            print("[INFO] Auto-triggering policy generation after successful summary...")
            policy_result = policy_generation_tool(f"Session ID: {session_id}")
            print(f"[INFO] Policy generation result: {policy_result}")
        except Exception as e:
            print(f"[WARNING] Policy generation failed but continuing: {e}")
        return str(comprehensive_summary)
        
    except Exception as e:
        error_msg = f"Summary generation error: {str(e)}"
        log_agent_status('summary_generation', 'Summary generation failed', str(e))
        return error_msg

# Main Orchestrator
class UnderwritingOrchestrator:
    """Orchestrates the complete underwriting workflow using 8 specialized agents"""
    
    def __init__(self):
        try:
            # Validate credentials before creating orchestrator
            is_valid, _ = validate_aws_credentials()
            if not is_valid:
                print("[ERROR] Cannot create orchestrator - AWS credentials invalid")
                self.orchestrator = None
                return
                
            if nova_pro is None:
                print("[ERROR] Nova Pro model not available")
                self.orchestrator = None
                return
            
            self.orchestrator = Agent(
                model=nova_pro,
                tools=[
                    data_intake_tool,
                    document_verification_tool,
                    medical_risk_assessment_tool,
                    financial_analysis_tool,
                    driving_analysis_tool,
                    compliance_analysis_tool,
                    lifestyle_behavioral_analysis_tool,
                    summary_generation_tool
                ],
                system_prompt=f"""You are the Chief Underwriting Orchestrator for Insurance responsible for coordinating comprehensive underwriting analysis using 8 specialized Nova Pro AI agents.

MANDATORY EXECUTION SEQUENCE:
You MUST execute ALL 8 agents in this exact order, regardless of any warnings, errors, or issues found in the end when summary agent generates the the summary in that all warnings and error will be highlighted seprately :

1. data_intake_tool - Process document intake and initial data extraction
2. document_verification_tool - Verify document completeness and authenticity
3. medical_risk_assessment_tool - Analyze medical records and assess health-related risks
4. financial_analysis_tool - Analyze financial capacity and coverage appropriateness
5. driving_analysis_tool - Analyze driving records and motor vehicle history
6. compliance_analysis_tool - Verify regulatory compliance and documentation requirements
7. lifestyle_behavioral_analysis_tool - Analyze lifestyle and behavioral risk factors
8. summary_generation_tool - Generate comprehensive underwriting summary with final decision

CRITICAL RULES:
- NEVER stop the workflow due to fraud indicators, compliance issues, or any warnings
- If document_verification_tool finds date discrepancies or potential fraud â†’ CONTINUE to medical_risk_assessment_tool and so on with other agents as well
- If any agent reports errors or concerns â†’ DOCUMENT them and CONTINUE to the next agent
- ALL 8 agents must be executed completely before generating the final summary
- The summary_generation_tool will consolidate ALL findings including warnings and issues

EXECUTION REQUIREMENTS:
- Call each tool exactly once in the specified sequence
- Wait for each tool to complete before proceeding to the next
- Collect all results and pass them to summary_generation_tool
- Return ONLY the final HTML summary from summary_generation_tool
- Do not display intermediate agent outputs - only the final comprehensive summary

UNDERWRITING PARAMETERS:
Coverage Limits: {UNDERWRITING_GUIDELINES['coverage_limits']['min_coverage']} to {UNDERWRITING_GUIDELINES['coverage_limits']['max_coverage']} USD
Age Limits: {UNDERWRITING_GUIDELINES['age_limits']['min_age']} to {UNDERWRITING_GUIDELINES['age_limits']['max_age']} years
Risk Categories: {list(UNDERWRITING_GUIDELINES['risk_categories'].keys())}

Execute the complete 8-agent underwriting workflow and return the comprehensive HTML summary with all findings consolidated."""
            )
            print("[INFO]  Underwriting Orchestrator initialized successfully with 8 specialized agents")
            
        except Exception as e:
            print(f"[ERROR] Failed to create orchestrator: {e}")
            self.orchestrator = None
    
    def process_underwriting(self, underwriting_input: str, session_id: str):
        """Process underwriting application with enhanced error handling"""
        try:
            # Pre-flight checks
            is_valid, _ = validate_aws_credentials()
            if not is_valid:
                return f"""<div class="underwriting-summary">
<h1>Insurance Underwriting Summary - Credential Error</h1>
<div class="error-info">
<h2>Error Information</h2>
<p><strong>Session ID:</strong> {session_id}</p>
<p><strong>Error:</strong> AWS credentials not configured properly or expired</p>
<p><strong>Date:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
</div>
<div class="next-steps">
<h2>Required Actions</h2>
<p>1. Check AWS credential configuration:</p>
<ul>
<li>Verify AWS_ACCESS_KEY_ID is set</li>
<li>Verify AWS_SECRET_ACCESS_KEY is set</li>
<li>Verify AWS_SESSION_TOKEN is set (for temporary credentials)</li>
<li>Verify AWS_REGION is set</li>
</ul>
<p>2. Ensure credentials haven't expired</p>
<p>3. Refresh temporary credentials if using session tokens</p>
<p>4. Restart the application after fixing credentials</p>
</div>
</div>"""

            reset_context_for_session(session_id)
            
            if session_id not in underwriting_input:
                underwriting_input = f"Session ID: {session_id}\n{underwriting_input}"
            
            print(f"[PROCESS] Starting 8-agent underwriting analysis for session: {session_id}")
            print("=" * 80)
            
            if self.orchestrator is None:
                print("[WARNING] Orchestrator not available, using manual processing")
                return self.manual_process_underwriting(underwriting_input, session_id)
            
            result = self.orchestrator(underwriting_input)
            
            print("=" * 80)
            print(f"[COMPLETE] 8-agent underwriting analysis completed for session: {session_id}")
            
            return result
            
        except Exception as e:
            print(f"[ERROR] Orchestrator processing error: {e}")
            return self.manual_process_underwriting(underwriting_input, session_id)
    
    def manual_process_underwriting(self, underwriting_input: str, session_id: str):
        """Manual processing when orchestrator fails - executes all 8 agents sequentially"""
        try:
            print(f"[PROCESS] Starting manual 8-agent processing for session: {session_id}")
            
            agents = [
                ('data_intake', data_intake_tool),
                ('document_verification', document_verification_tool),
                ('medical_risk_assessment', medical_risk_assessment_tool),
                ('financial', financial_analysis_tool),
                ('driving', driving_analysis_tool),
                ('compliance', compliance_analysis_tool),
                ('lifestyle_behavioral', lifestyle_behavioral_analysis_tool),
                ('summary_generation', summary_generation_tool)
            ]
            
            for agent_name, agent_tool in agents:
                try:
                    print(f"[PROCESS] Processing {agent_name} agent")
                    result = agent_tool(underwriting_input)
                    print(f"\n[AGENT_RESULT] {agent_name.upper()}:\n{result}\n" + "="*80 + "\n")
                    
                    if agent_name == 'summary_generation':
                        return result
                        
                except Exception as e:
                    print(f"[ERROR] Agent {agent_name} failed: {e}")
                    continue
            
            # Fallback summary if processing fails
            context = get_or_create_context(session_id)
            all_insights = context.get_all_insights()
            
            fallback_summary = f"""<div class="underwriting-summary">
<h1>Trianz Insurance Underwriting Summary</h1>

<div class="session-info">
<h2>Session Information</h2>
<p><strong>Session ID:</strong> {session_id}</p>
<p><strong>Processing Date:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
<p><strong>Status:</strong> Partial Processing Completed</p>
<p><strong>Agents Processed:</strong> {len(all_insights)} of 8</p>
</div>

<div class="agent-results">
<h2>Specialist Analysis Results</h2>"""
            
            for agent_name, analysis in all_insights.items():
                fallback_summary += f"""<div class="agent-analysis">
<h3>{agent_name.replace('_', ' ').title()} Analysis</h3>
<div class="analysis-content">
<p>{analysis}</p>
</div>
</div>"""
            
            fallback_summary += """</div>

<div class="processing-note">
<h2>Processing Status</h2>
<p>This summary represents partial underwriting analysis. Some specialist components may require manual review or additional processing. Please contact Trianz underwriting support for complete analysis if needed.</p>
</div>
</div>"""
            
            return fallback_summary
            
        except Exception as e:
            print(f"[ERROR] Manual processing error: {e}")
            return f"""<div class="underwriting-summary">
<h1>Insurance Underwriting Summary - Processing Error</h1>
<div class="error-info">
<h2>Error Information</h2>
<p><strong>Session ID:</strong> {session_id}</p>
<p><strong>Error:</strong> Underwriting processing failed - {str(e)}</p>
<p><strong>Date:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
</div>
<div class="next-steps">
<h2>Next Steps</h2>
<p>Please contact underwriting support for manual review and processing assistance.</p>
</div>
</div>"""

# Initialize the orchestrator
underwriting_orchestrator = UnderwritingOrchestrator()



def check_system_status():
    """Check overall system status and configuration"""
    print("\n" + "="*60)
    print("UNDERWRITING SYSTEM STATUS CHECK")
    print("="*60)
    
    # Check AWS credentials
    is_valid, session = validate_aws_credentials()
    print(f"AWS Credentials: {'Ã¢Å“â€œ Valid' if is_valid else 'Ã¢Å“â€” Invalid'}")
    
    # Check Nova Pro model
    print(f"Nova Pro Model: {'Ã¢Å“â€œ Available' if nova_pro else 'Ã¢Å“â€” Not Available'}")
    
    # Check agents
    agents_status = [
        ('Data Intake', data_intake_agent),
        ('Document Verification', document_verification_agent),
        ('Medical Risk Assessment', medical_risk_assessment_agent),
        ('Financial Analysis', financial_agent),
        ('Driving Analysis', driving_agent),
        ('Compliance Analysis', compliance_agent),
        ('Lifestyle Behavioral', lifestyle_behavioral_agent),
        ('Summary Generation', summary_generation_agent)
    ]
    
    print("\nAgent Status:")
    for agent_name, agent in agents_status:
        status = "Ã¢Å“â€œ Ready" if agent else "Ã¢Å“â€” Not Available"
        print(f"  {agent_name}: {status}")
    
    
    print(f"\nOrchestrator: {'Ã¢Å“â€œ Ready' if underwriting_orchestrator.orchestrator else 'Ã¢Å“â€” Not Available'}")
    

    print(f"Upload Folder: {'Ã¢Å“â€œ Exists' if os.path.exists(UPLOAD_FOLDER) else 'Ã¢Å“â€” Missing'} ({UPLOAD_FOLDER})")
    
    print("="*60)
    print("SYSTEM READY" if is_valid and nova_pro else "SYSTEM NOT READY - CHECK CONFIGURATION")
    print("="*60 + "\n")

def get_session_status(session_id: str):
    """Get detailed status for a specific session"""
    if session_id in context_registry:
        context = context_registry[session_id]
        return {
            'session_id': session_id,
            'processed_agents': list(context.processed_agents),
            'total_agents': 8,
            'completion_percentage': (len(context.processed_agents) / 8) * 100,
            'processing_start_time': context.processing_start_time.isoformat() if context.processing_start_time else None,
            'status': 'completed' if len(context.processed_agents) == 8 else 'in_progress',
            'document_content_length': len(context.document_content) if context.document_content else 0
        }
    else:
        return {'error': f'Session {session_id} not found'}

def cleanup_old_sessions(max_age_hours=24):
    """Clean up old session data"""
    try:
        current_time = datetime.now()
        cleaned_sessions = []
        
        for session_id, context in list(context_registry.items()):
            if context.processing_start_time:
                age = current_time - context.processing_start_time
                if age.total_seconds() > (max_age_hours * 3600):
                    del context_registry[session_id]
                    cleaned_sessions.append(session_id)
        
        
        if os.path.exists(UPLOAD_FOLDER):
            for session_folder in os.listdir(UPLOAD_FOLDER):
                session_path = os.path.join(UPLOAD_FOLDER, session_folder)
                if os.path.isdir(session_path):
                    try:
                        mod_time = datetime.fromtimestamp(os.path.getmtime(session_path))
                        age = current_time - mod_time
                        if age.total_seconds() > (max_age_hours * 3600):
                            import shutil
                            shutil.rmtree(session_path)
                            cleaned_sessions.append(session_folder)
                    except Exception as e:
                        print(f"[WARNING] Failed to clean session folder {session_folder}: {e}")
        
        if cleaned_sessions:
            print(f"[INFO] Cleaned up {len(cleaned_sessions)} old sessions")
        
        return cleaned_sessions
    except Exception as e:
        print(f"[ERROR] Session cleanup failed: {e}")
        return []


__all__ = [
    'UnderwritingOrchestrator',
    'underwriting_orchestrator', 
    'document_processor',
    'get_or_create_context',
    'reset_context_for_session',
    'extract_session_id',
    'check_system_status',
    'get_session_status',
    'cleanup_old_sessions',
    'validate_aws_credentials'
]


if __name__ == "__main__":
    check_system_status()
    print("[INFO] Underwriting System loaded and ready")
    print("[INFO] Key functions available:")
    print("  - underwriting_orchestrator.process_underwriting(input, session_id)")
    print("  - check_system_status()")
    print("  - get_session_status(session_id)")
    print("  - cleanup_old_sessions()")
    
  
    print(f"\n[TEST] Current AWS Region: {os.getenv('AWS_REGION', 'Not set')}")
    print(f"[TEST] Access Key ID: {os.getenv('AWS_ACCESS_KEY_ID', 'Not set')[:8]}..." if os.getenv('AWS_ACCESS_KEY_ID') else "[TEST] Access Key ID: Not set")
    print(f"[TEST] Session Token: {'Available' if os.getenv('AWS_SESSION_TOKEN') else 'Not Available'}")