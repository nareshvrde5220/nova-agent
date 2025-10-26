import os
import json
import logging
import traceback
import tempfile
import re
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


app = BedrockAgentCoreApp()


try:
    memory_client = MemoryClient()
    logger.info("AgentCore Memory Client initialized successfully")
except Exception as e:
    logger.warning(f"AgentCore Memory Client initialization failed: {e}")
    memory_client = None

# Import your existing system with error handling
try:
    from underwriting_agents import (
        underwriting_orchestrator, 
        document_processor,
        get_or_create_context,
        validate_aws_credentials,
        check_system_status
    )
    from config import (
        UNDERWRITING_GUIDELINES, 
        REQUIRED_DOCUMENTS, 
        RISK_SCORING_RULES,
        BUSINESS_RULES,
        LOCAL_CONFIG
    )
    logger.info("Successfully imported underwriting system")
except ImportError as e:
    logger.error(f"Failed to import underwriting system: {e}")
    underwriting_orchestrator = None
    document_processor = None

class UnderwritingAgent:
    """Enhanced AgentCore-compatible Underwriting Agent with hybrid local-cloud support"""
    
    def __init__(self):
        self.s3_client = None
        self.s3_bucket = 'trianz-aws-hackathon'
        self.setup_aws_services()
        self.validate_system()
    
    def setup_aws_services(self):
        """Initialize AWS services with enhanced error handling"""
        try:
        
            region = os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION') or 'us-east-1'
        
            self.s3_client = boto3.client('s3', region_name=region)
            logger.info(f"AWS S3 client initialized successfully with region: {region}")
           
            self.s3_client.head_bucket(Bucket=self.s3_bucket)
            logger.info(f"S3 bucket access confirmed: {self.s3_bucket}")
            
        except Exception as e:
            logger.error(f"Failed to initialize AWS services: {e}")
            self.s3_client = None
    
    def validate_system(self):
        """Enhanced system validation"""
        try:
            if underwriting_orchestrator is None:
                logger.error("Underwriting orchestrator not available")
                return False
                
          
            is_valid, _ = validate_aws_credentials()
            if not is_valid:
                logger.error("AWS credentials validation failed")
                return False
            
            
            if not self.s3_client:
                logger.error("S3 client not available")
                return False
                
            logger.info("System validation successful")
            return True
        except Exception as e:
            logger.error(f"System validation failed: {e}")
            return False
    
    def process_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Enhanced main entry point for underwriting requests"""
        try:
            request_type = payload.get('request_type', 'unknown')
            session_id = payload.get('session_id')
            
            logger.info(f"Processing {request_type} request for session {session_id}")
            
           
            if request_type == 'create_session':
                return self.handle_create_session(payload)
            elif request_type == 's3_process':
                return self.handle_s3_document_processing(payload)
            elif request_type == 'get_agent_status':
                return self.handle_get_agent_status_from_s3(payload)
            elif request_type == 'get_status':
                return self.handle_status_request(payload)
            elif request_type == 'get_summary':
                return self.handle_summary_request(payload)
            elif request_type == 'upload_documents':
                return self.handle_document_upload(payload)
            elif request_type == 'start_underwriting':
                return self.handle_underwriting_analysis(payload)
            else:
                return self.handle_general_query(payload)
                
        except Exception as e:
            logger.error(f"Error processing request: {e}")
            logger.error(traceback.format_exc())
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat(),
                'request_type': payload.get('request_type', 'unknown')
            }
    
    def handle_create_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Enhanced session creation with proper S3 folder structure"""
        try:
            # Generate new session with timestamp
            timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            unique_id = str(uuid.uuid4())[:8]
            session_id = f"session_{timestamp}_{unique_id}"
            
            logger.info(f"Creating new session: {session_id}")
            
            # Create session folder in S3 by creating a placeholder file
            try:
                placeholder_key = f"{session_id}/.session_initialized"
                self.s3_client.put_object(
                    Bucket=self.s3_bucket,
                    Key=placeholder_key,
                    Body=json.dumps({
                        'session_id': session_id,
                        'created_at': datetime.now().isoformat(),
                        'status': 'initialized',
                        'folder_purpose': 'Session folder for Trianz underwriting documents and status'
                    }, indent=2),
                    ContentType='application/json'
                )
                
                logger.info(f"S3 session folder created: s3://{self.s3_bucket}/{session_id}/")
                
            except Exception as e:
                logger.warning(f"Could not create S3 session folder: {e}")
                # Continue anyway, folder will be created when first file is uploaded
            
            return {
                'status': 'success',
                'session_id': session_id,
                's3_bucket': self.s3_bucket,
                'session_folder': f"s3://{self.s3_bucket}/{session_id}/",
                'message': f'Session {session_id} created successfully',
                'timestamp': datetime.now().isoformat(),
                'ready_for_upload': True
            }
            
        except Exception as e:
            logger.error(f"Session creation error: {e}")
            return {
                'status': 'error',
                'error': f"Session creation failed: {str(e)}",
                'timestamp': datetime.now().isoformat()
            }
    
    def handle_s3_document_processing(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Enhanced S3 document processing with better error handling"""
        try:
            s3_bucket = payload.get('s3_bucket', self.s3_bucket)
            s3_key = payload.get('s3_key')
            session_id = payload.get('session_id')
            
            # Validate required parameters
            if not all([s3_bucket, s3_key]):
                return {
                    'status': 'error', 
                    'error': 'Missing required parameters: s3_bucket and s3_key are required',
                    'session_id': session_id or 'unknown'
                }
            
            # Extract session_id from s3_key if not provided
            if not session_id:
                session_id = self.extract_session_from_s3_key(s3_key)
                if not session_id:
                    return {
                        'status': 'error',
                        'error': 'Session ID could not be determined from S3 key',
                        's3_key': s3_key
                    }
            
            logger.info(f"Processing S3 file s3://{s3_bucket}/{s3_key} for session {session_id}")
            
            # Validate system readiness
            #if not self.validate_system():
                #return {
                    #'status': 'error',
                    #'error': 'System validation failed - check AWS credentials and agent configuration',
                    #'session_id': session_id
                #}
            
            
            self.initialize_processing_status(session_id)
            
            
            return self._process_s3_file(s3_bucket, s3_key, session_id)
            
        except Exception as e:
            logger.error(f"S3 document processing error: {e}")
            return {
                'status': 'error', 
                'error': f"S3 processing failed: {str(e)}",
                'session_id': payload.get('session_id', 'unknown')
            }
    
    def extract_session_from_s3_key(self, s3_key: str) -> Optional[str]:
        """Extract session ID from S3 key path"""
        try:
            # Match session format: session_YYYY-MM-DD_HH-MM-SS_uniqueid
            pattern = r'(session_[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}_[a-f0-9]{8})'
            match = re.search(pattern, s3_key)
            if match:
                return match.group(1)
            
            # Fallback: assume first part of path is session ID
            parts = s3_key.split('/')
            if len(parts) > 1 and parts[0].startswith('session_'):
                return parts[0]
                
            return None
        except Exception as e:
            logger.error(f"Failed to extract session ID from S3 key {s3_key}: {e}")
            return None
    
    def initialize_processing_status(self, session_id: str):
        """Initialize processing status in S3"""
        try:
            status_data = {
                'session_id': session_id,
                'created_at': datetime.now().isoformat(),
                'last_updated': datetime.now().isoformat(),
                'status': 'starting',
                'agents': {
                    'data_intake': {'status': 'pending', 'analysis': '', 'timestamp': ''},
                    'document_verification': {'status': 'pending', 'analysis': '', 'timestamp': ''},
                    'medical_risk_assessment': {'status': 'pending', 'analysis': '', 'timestamp': ''},
                    'financial': {'status': 'pending', 'analysis': '', 'timestamp': ''},
                    'driving': {'status': 'pending', 'analysis': '', 'timestamp': ''},
                    'compliance': {'status': 'pending', 'analysis': '', 'timestamp': ''},
                    'lifestyle_behavioral': {'status': 'pending', 'analysis': '', 'timestamp': ''},
                    'summary_generation': {'status': 'pending', 'analysis': '', 'timestamp': ''}
                },
                'processing_summary': {
                    'total_agents': 8,
                    'completed_agents': 0,
                    'pending_agents': 8,
                    'completion_percentage': 0
                }
            }
            
            s3_key = f"{session_id}/agent_status.json"
            self.s3_client.put_object(
                Bucket=self.s3_bucket,
                Key=s3_key,
                Body=json.dumps(status_data, indent=2, ensure_ascii=False),
                ContentType='application/json'
            )
            
            logger.info(f"Processing status initialized in S3: s3://{self.s3_bucket}/{s3_key}")
            
        except Exception as e:
            logger.warning(f"Failed to initialize processing status: {e}")
    
    def _process_s3_file(self, s3_bucket: str, s3_key: str, session_id: str) -> Dict[str, Any]:
        """Enhanced S3 file processing with comprehensive error handling"""
        temp_file_path = None
        
        try:
            # Create temporary file for download
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_file:
                temp_file_path = temp_file.name
                
                # Download from S3
                logger.info(f"Downloading s3://{s3_bucket}/{s3_key}")
                self.s3_client.download_file(s3_bucket, s3_key, temp_file_path)
                
                file_size = os.path.getsize(temp_file_path)
                logger.info(f"Downloaded {file_size} bytes successfully")
                
                # Validate file
                if file_size == 0:
                    raise Exception("Downloaded file is empty")
                
                if file_size > 50 * 1024 * 1024:  # 50MB limit
                    raise Exception("File exceeds 50MB limit")
            
            # Extract documents
            logger.info("Extracting ZIP file...")
            extraction_result = document_processor.extract_zip_to_session(temp_file_path, session_id)
            
            if 'error' in extraction_result:
                return {
                    'status': 'error',
                    'error': f"Document extraction failed: {extraction_result['error']}",
                    'session_id': session_id
                }
            
            doc_count = extraction_result.get('total_count', 0)
            logger.info(f"Successfully extracted {doc_count} documents")
            
            if doc_count == 0:
                return {
                    'status': 'error',
                    'error': 'No PDF documents found in ZIP file',
                    'session_id': session_id
                }
            
            # Update status to processing
            self.update_processing_status(session_id, 'processing', f'Extracted {doc_count} documents, starting agent analysis')
            
            # Run underwriting analysis
            logger.info("Starting comprehensive underwriting analysis...")
            underwriting_input = f"""
Session ID: {session_id}
S3 Source: s3://{s3_bucket}/{s3_key}
Processing Request: Complete 8-agent underwriting analysis
Document Count: {doc_count}
Processing Timestamp: {datetime.now().isoformat()}

Execute comprehensive underwriting workflow for all extracted documents.
            """
            
            # Execute the 8-agent workflow
            result = underwriting_orchestrator.process_underwriting(underwriting_input, session_id)
            
            # Get individual agent results from context
            context = get_or_create_context(session_id)
            individual_results = {}
            
            agent_names = ['data_intake', 'document_verification', 'medical_risk_assessment', 
                          'financial', 'driving', 'compliance', 'lifestyle_behavioral', 'summary_generation']
            
            for agent_name in agent_names:
                agent_data = context.agent_data.get(agent_name, {})
                individual_results[agent_name] = {
                    'analysis': agent_data.get('analysis', 'Not completed'),
                    'timestamp': agent_data.get('timestamp', ''),
                    'status': agent_data.get('status', 'pending')
                }
            
            # Update final status
            self.update_processing_status(session_id, 'completed', 'All agents completed successfully', str(result))
            
            logger.info("Underwriting analysis completed successfully")
            policy_info = {}
            policy_data = context.agent_data.get('policy_generation', {})
            if policy_data and policy_data.get('status') == 'completed':
                try:
                    policy_details = json.loads(policy_data.get('analysis', '{}'))
                    policy_info = {
                        'policy_generated': True,
                        's3_location': policy_details.get('s3_location', ''),
                        's3_key': policy_details.get('s3_key', ''),
                        'local_file': policy_details.get('local_file', ''),
                        'policy_number': policy_details.get('policy_number', 'N/A')
                    }
                except:
                    policy_info = {'policy_generated': False}
            else:
                policy_info = {'policy_generated': False}
            return {
                'status': 'success',
                'session_id': session_id,
                's3_source': f"s3://{s3_bucket}/{s3_key}",
                'documents_processed': doc_count,
                'underwriting_complete': True,
                'agents_executed': 8,
                'final_summary': str(result),
                'individual_agent_results': individual_results,
                'policy_info': policy_info,
                'processing_summary': {
                    'total_agents': 8,
                    'completed_agents': len([r for r in individual_results.values() if r['status'] == 'completed']),
                    'completion_percentage': (len([r for r in individual_results.values() if r['status'] == 'completed']) / 8) * 100,
                    'session_folder': f"s3://{s3_bucket}/{session_id}/",
                    'agent_status_file': f"s3://{s3_bucket}/{session_id}/agent_status.json"
                },
                'message': f'Successfully processed {doc_count} documents and completed comprehensive underwriting analysis'
            }
            
        except Exception as e:
            logger.error(f"Error processing S3 file: {e}")
            self.update_processing_status(session_id, 'failed', f'Processing failed: {str(e)}')
            return {
                'status': 'error',
                'error': f"Processing failed: {str(e)}",
                'session_id': session_id
            }
        
        finally:
            # Clean up temporary file
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                    logger.info("Cleaned up temporary file")
                except Exception as e:
                    logger.warning(f"Failed to clean up temp file: {e}")
    
    def update_processing_status(self, session_id: str, status: str, message: str, final_summary: str = ''):
        """Update processing status in S3"""
        try:
            s3_key = f"{session_id}/agent_status.json"
            
            # Try to get existing status
            try:
                response = self.s3_client.get_object(Bucket=self.s3_bucket, Key=s3_key)
                status_data = json.loads(response['Body'].read().decode('utf-8'))
            except:
                # Create new status if doesn't exist
                status_data = {
                    'session_id': session_id,
                    'created_at': datetime.now().isoformat(),
                    'agents': {},
                    'processing_summary': {}
                }
            
            # Update status
            status_data['status'] = status
            status_data['last_updated'] = datetime.now().isoformat()
            status_data['message'] = message
            
            if final_summary:
                status_data['final_summary'] = final_summary
            
            # Save back to S3
            self.s3_client.put_object(
                Bucket=self.s3_bucket,
                Key=s3_key,
                Body=json.dumps(status_data, indent=2, ensure_ascii=False),
                ContentType='application/json'
            )
            
            logger.info(f"Status updated in S3: {status} - {message}")
            
        except Exception as e:
            logger.warning(f"Failed to update processing status: {e}")
    
    def handle_get_agent_status_from_s3(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Get agent status directly from S3"""
        try:
            session_id = payload.get('session_id')
            
            if not session_id:
                return {'status': 'error', 'error': 'Session ID required'}
            
            # Read agent status from S3
            s3_key = f"{session_id}/agent_status.json"
            
            try:
                response = self.s3_client.get_object(Bucket=self.s3_bucket, Key=s3_key)
                agent_status = json.loads(response['Body'].read().decode('utf-8'))
                
                return {
                    'status': 'success',
                    'session_id': session_id,
                    'agent_status': agent_status,
                    's3_location': f"s3://{self.s3_bucket}/{s3_key}"
                }
                
            except Exception as e:
                return {
                    'status': 'error',
                    'error': f'Agent status not found in S3: {str(e)}',
                    'session_id': session_id
                }
                
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
    
    def handle_status_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle status check requests with S3 integration"""
        try:
            session_id = payload.get('session_id')
            
            if not session_id:
                return {'status': 'error', 'error': 'Session ID required'}
            
            # Get status from S3
            s3_key = f"{session_id}/agent_status.json"
            
            try:
                response = self.s3_client.get_object(Bucket=self.s3_bucket, Key=s3_key)
                s3_status = json.loads(response['Body'].read().decode('utf-8'))
            except:
                s3_status = {'status': 'not_found'}
            
            # Get memory data if available
            memory_data = {}
            if memory_client:
                try:
                    memory_response = memory_client.get(session_id=session_id)
                    memory_data = memory_response.get('memory_data', {}) if memory_response else {}
                except Exception as e:
                    logger.warning(f"Failed to retrieve from memory: {e}")
            
            return {
                'status': 'success',
                'session_id': session_id,
                's3_status': s3_status,
                'memory_data': memory_data,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Status request error: {e}")
            return {'status': 'error', 'error': str(e)}
    
    def handle_summary_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle summary/results requests from S3"""
        try:
            session_id = payload.get('session_id')
            
            if not session_id:
                return {'status': 'error', 'error': 'Session ID required'}
            
            # Get summary from S3
            s3_key = f"{session_id}/agent_status.json"
            
            try:
                response = self.s3_client.get_object(Bucket=self.s3_bucket, Key=s3_key)
                status_data = json.loads(response['Body'].read().decode('utf-8'))
                
                return {
                    'status': 'success',
                    'session_id': session_id,
                    'summary_data': status_data,
                    'underwriting_result': status_data.get('final_summary', 'No results available'),
                    'agent_results': status_data.get('agents', {}),
                    'timestamp': datetime.now().isoformat()
                }
                
            except Exception as e:
                return {
                    'status': 'error',
                    'error': f'Summary not found in S3: {str(e)}',
                    'session_id': session_id
                }
            
        except Exception as e:
            logger.error(f"Summary request error: {e}")
            return {'status': 'error', 'error': str(e)}
    
    def handle_document_upload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle document upload information"""
        try:
            session_id = payload.get('session_id')
            if not session_id:
                timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
                unique_id = str(uuid.uuid4())[:8]
                session_id = f"session_{timestamp}_{unique_id}"
            
            return {
                'status': 'success',
                'session_id': session_id,
                'message': 'Document upload endpoint ready for hybrid local-cloud integration',
                'upload_location': f"s3://{self.s3_bucket}/{session_id}/documents/",
                's3_bucket': self.s3_bucket
            }
            
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
    
    def handle_underwriting_analysis(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle underwriting analysis requests"""
        try:
            session_id = payload.get('session_id')
            
            if not session_id:
                return {'status': 'error', 'error': 'Session ID required for underwriting analysis'}
            
            return {
                'status': 'success',
                'session_id': session_id,
                'message': 'Underwriting analysis endpoint ready for hybrid processing',
                'next_steps': 'Use s3_process for document processing with session_id',
                's3_bucket': self.s3_bucket
            }
            
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
    
    def handle_general_query(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle general queries with enhanced system information"""
        try:
            prompt = payload.get('prompt', '')
            
            # System status query
            if any(word in prompt.lower() for word in ['status', 'health', 'check']):
                try:
                    check_system_status()
                    return {
                        'status': 'success',
                        'message': 'Trianz Underwriting & Policy Generation System operational in AgentCore with hybrid local-cloud support',
                        'system_info': {
                            'platform': 'AWS AgentCore',
                            'agents_available': 8,
                            'model': 'Amazon Nova Pro',
                            's3_bucket': self.s3_bucket,
                            'hybrid_mode': 'Local frontend + Cloud backend',
                            'capabilities': [
                                'Session creation and management',
                                'S3 document processing',
                                '8-agent underwriting workflow',
                                'Real-time status tracking',
                                'Risk assessment and compliance verification',
                                'HTML report generation',
                                'Dynamic session management',
                                'S3 status tracking for frontend integration'
                            ]
                        }
                    }
                except Exception as e:
                    return {
                        'status': 'warning',
                        'message': 'System check completed with issues',
                        'error': str(e)
                    }
            
            # Default response
            return {
                'status': 'success',
                'message': 'Trianz Underwriting & policy generation system ready for hybrid local-cloud processing',
                'usage_instructions': {
                    'create_session': 'Create new session: {"request_type": "create_session"}',
                    's3_process': 'Process documents from S3: {"request_type": "s3_process", "s3_bucket": "bucket", "s3_key": "session_id/file.zip", "session_id": "session-id"}',
                    'get_agent_status': 'Check agent status from S3: {"request_type": "get_agent_status", "session_id": "your-session-id"}',
                    'get_status': 'Check processing status: {"request_type": "get_status", "session_id": "your-id"}',
                    'get_summary': 'Get analysis results: {"request_type": "get_summary", "session_id": "your-id"}'
                },
                'features': {
                    'hybrid_architecture': 'Local Flask frontend + Cloud AgentCore backend',
                    'session_management': 'Create and manage isolated sessions with S3 folders',
                    'dynamic_sessions': 'Auto-generated session IDs with timestamps',
                    's3_storage': 'Agent status stored in S3 for real-time frontend access',
                    'real_time_updates': 'JSON updates after each agent completion',
                    'individual_results': 'Access to each agent\'s analysis results',
                    'auto_processing': 'Automatic AgentCore trigger on file upload'
                },
                's3_bucket': self.s3_bucket
            }
            
        except Exception as e:
            logger.error(f"General query error: {e}")
            return {'status': 'error', 'error': str(e)}


trianz_agent = UnderwritingAgent()

@app.entrypoint
def invoke(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Enhanced AgentCore entrypoint for hybrid  Underwriting System"""
    
    logger.info(f"AgentCore invoke called with payload: {payload}")
    
    try:
        
        actual_payload = payload
        
       
        if "message" in payload and isinstance(payload["message"], str):
            message = payload["message"]
            logger.info(f"Processing message: {message}")
            
            try:
                actual_payload = json.loads(message)
                logger.info(f"Successfully parsed JSON payload: {actual_payload}")
            except json.JSONDecodeError:
                logger.info("Direct JSON parsing failed, attempting manual parsing...")
                
                
                try:
                    
                    parsed = {}
                    
                   
                    patterns = {
                        'request_type': r'request_type["\']?\s*:\s*["\']?([^,}"\'\s]+)',
                        'session_id': r'session_id["\']?\s*:\s*["\']?([^,}"\'\s]+)',
                        's3_bucket': r's3_bucket["\']?\s*:\s*["\']?([^,}"\'\s]+)',
                        's3_key': r's3_key["\']?\s*:\s*["\']?([^,}"\'\s]+)'
                    }
                    
                    for key, pattern in patterns.items():
                        match = re.search(pattern, message)
                        if match:
                            value = match.group(1).strip().strip('"\'')
                            parsed[key] = value
                    
                    if parsed:
                        actual_payload = parsed
                        logger.info(f"Manual parsing successful: {actual_payload}")
                    else:
                       
                        actual_payload = {"prompt": message}
                        
                except Exception as parse_error:
                    logger.warning(f"All parsing attempts failed: {parse_error}")
                    actual_payload = {"prompt": message}
        
        
        result = trianz_agent.process_request(actual_payload)
        
        logger.info(f"Request processed with status: {result.get('status', 'unknown')}")
        return result
        
    except Exception as e:
        logger.error(f"Fatal error in invoke: {e}")
        logger.error(traceback.format_exc())
        
        return {
            'status': 'error',
            'error': f'AgentCore processing failed: {str(e)}',
            'timestamp': datetime.now().isoformat(),
            'debug_info': {
                'payload_received': str(payload),
                'error_trace': traceback.format_exc()
            }
        }

if __name__ == "__main__":
    logger.info("Starting Trianz Underwriting & Policy Generation AgentCore application with hybrid local-cloud support...")
    app.run()