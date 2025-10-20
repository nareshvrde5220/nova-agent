import os
import json
import uuid
import base64
import asyncio
import traceback
import sys
import io
import wave
from datetime import datetime
from typing import Dict, Any, Optional

from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient, InvokeModelWithBidirectionalStreamOperationInput
from aws_sdk_bedrock_runtime.models import InvokeModelWithBidirectionalStreamInputChunk, BidirectionalInputPayloadPart
from aws_sdk_bedrock_runtime.config import Config, HTTPAuthSchemeResolver, SigV4AuthScheme
from smithy_aws_core.credentials_resolvers.environment import EnvironmentCredentialsResolver

INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000
CHANNELS = 1
SAMPLE_WIDTH = 2


def log_exception(exc):
    print(f"[SONIC ERROR] {exc}", file=sys.stderr)
    traceback.print_exc()


def pcm_to_wav_bytes(pcm_bytes, sample_rate=OUTPUT_SAMPLE_RATE, channels=CHANNELS, sample_width=SAMPLE_WIDTH):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buffer.getvalue()


class TrianzUnderwritingConversation:
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.conversation_started = datetime.now().isoformat()
        
        self.personal_info = {
            'full_name': None,
            'date_of_birth': None,
            'age': None,
            'phone': None,
            'email': None,
            'address': {
                'street': None,
                'city': None,
                'state': None,
                'zip': None
            },
            'ssn': None,
            'citizenship': None
        }
        
        self.policy_info = {
            'policy_type': None,
            'coverage_amount': None,
            'policy_term': None,
            'primary_beneficiary': {
                'name': None,
                'relationship': None,
                'dob': None
            },
            'contingent_beneficiary': {
                'name': None,
                'relationship': None,
                'dob': None
            }
        }
        
        self.financial_info = {
            'occupation': None,
            'employer': None,
            'employment_duration': None,
            'annual_income': None,
            'additional_income': None,
            'household_income': None,
            'existing_policies': None,
            'net_worth': None,
            'home_ownership': None,
            'mortgage_balance': None
        }
        
        self.health_info = {
            'height': None,
            'weight': None,
            'tobacco_user': None,
            'tobacco_quit_date': None,
            'medical_conditions': {
                'heart_disease': None,
                'diabetes': None,
                'cancer': None,
                'stroke': None,
                'kidney_disease': None,
                'mental_health': None,
                'sleep_apnea': None
            },
            'medications': [],
            'hospitalizations': [],
            'surgeries': [],
            'pregnancy_status': None,
            'family_history': []
        }
        
        self.lifestyle_info = {
            'alcohol_consumption': None,
            'substance_abuse_history': None,
            'high_risk_activities': [],
            'exercise_routine': None,
            'international_travel': []
        }
        
        self.driving_info = {
            'license_valid': None,
            'license_state': None,
            'violations': [],
            'accidents': [],
            'annual_mileage': None
        }
        
        self.additional_info = {
            'bankruptcy_history': None,
            'judgments_liens': None,
            'felony_conviction': None,
            'pending_lawsuits': None,
            'previous_decline': None,
            'other_applications': None,
            'business_purpose': None,
            'replacement_policy': None
        }
        
        self.conversation_history = []
        self.information_collected = {
            'personal': False,
            'policy': False,
            'financial': False,
            'health': False,
            'lifestyle': False,
            'driving': False,
            'additional': False
        }
        self.documents_ready = False
        self.upload_triggered = False
        
    def add_message(self, role: str, message: str):
        self.conversation_history.append({
            'role': role,
            'message': message,
            'timestamp': datetime.now().isoformat()
        })
    
    def extract_information(self, user_message: str):
        message_lower = user_message.lower()
        
        if 'name is' in message_lower or 'i am' in message_lower or "i'm" in message_lower:
            words = user_message.split()
            if 'is' in words:
                idx = words.index('is')
                if idx + 1 < len(words):
                    self.personal_info['full_name'] = ' '.join(words[idx+1:idx+3])
        
        # Policy type detection - mark as confirmed
        if 'silver' in message_lower:
            self.policy_info['policy_type'] = 'Silver'
            return True  # Policy selected
        elif 'gold' in message_lower:
            self.policy_info['policy_type'] = 'Gold'
            return True  # Policy selected
        elif 'platinum' in message_lower:
            self.policy_info['policy_type'] = 'Platinum'
            return True  # Policy selected
        
        if any(word in message_lower for word in ['smoke', 'smoking', 'smoker']):
            if any(word in message_lower for word in ['no', "don't", 'not', 'never']):
                self.health_info['tobacco_user'] = False
            elif any(word in message_lower for word in ['yes', 'do', 'currently']):
                self.health_info['tobacco_user'] = True
        
        if any(word in message_lower for word in ['drink', 'alcohol', 'drinking']):
            if 'never' in message_lower or 'no' in message_lower:
                self.lifestyle_info['alcohol_consumption'] = 'never'
            elif 'occasionally' in message_lower or 'rarely' in message_lower:
                self.lifestyle_info['alcohol_consumption'] = 'occasionally'
            elif 'moderate' in message_lower or 'social' in message_lower:
                self.lifestyle_info['alcohol_consumption'] = 'moderately'
        
        return False  # No policy selected
    
    def check_upload_request(self, message: str) -> bool:
        """Check if user is explicitly requesting upload/documents"""
        message_lower = message.lower()
        # More strict keywords - only when user ASKS for upload
        explicit_keywords = [
            'upload', 'link', 'send link', 'send me link', 
            'give me the link', 'where do i upload', 'upload link',
            'send me the upload', 'document link', 'how do i upload',
            'where to upload', 'upload documents', 'submit documents'
        ]
        
        # Check for explicit upload requests
        for keyword in explicit_keywords:
            if keyword in message_lower:
                return True
        
        # Also check for "ready" but only if it's about documents/upload
        if 'ready' in message_lower:
            if any(word in message_lower for word in ['document', 'upload', 'file', 'submit']):
                return True
        
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'session_id': self.session_id,
            'conversation_started': self.conversation_started,
            'personal_info': self.personal_info,
            'policy_info': self.policy_info,
            'financial_info': self.financial_info,
            'health_info': self.health_info,
            'lifestyle_info': self.lifestyle_info,
            'driving_info': self.driving_info,
            'additional_info': self.additional_info,
            'conversation_history': self.conversation_history,
            'information_collected': self.information_collected,
            'documents_ready': self.documents_ready,
            'upload_triggered': self.upload_triggered,
            'last_updated': datetime.now().isoformat()
        }


class NovaTrianzUnderwritingHandler:
    
    def __init__(self, sid: str, socketio):
        self.sid = sid
        self.socketio = socketio
        self.model_id = 'amazon.nova-sonic-v1:0'
        self.region = 'us-east-1'
        self.client = None
        self.stream = None
        self.is_active = False
        
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        unique_id = str(uuid.uuid4())[:8]
        self.session_id = f"session_{timestamp}_{unique_id}"
        
        # Simplified naming - like reference
        self.prompt_name = str(uuid.uuid4())
        self.content_name = str(uuid.uuid4())
        self.audio_content_name = str(uuid.uuid4())
        
        self.conversation = TrianzUnderwritingConversation(self.session_id)
        
        self.upload_triggered = False
        self.pending_upload_request = False
        self.policy_type_confirmed = False  # NEW: Track if policy selected
        
        self.role = None
        self.display_assistant_text = False
        
        self._setup_credentials()
        
        print(f"[NOVA] Trianz Underwriting Handler initialized for session: {self.session_id}")
    
    def _setup_credentials(self):
        try:
            if not (os.environ.get('AWS_ACCESS_KEY_ID') and os.environ.get('AWS_SECRET_ACCESS_KEY')):
                import boto3
                session = boto3.Session()
                credentials = session.get_credentials()
                if credentials:
                    os.environ['AWS_ACCESS_KEY_ID'] = credentials.access_key
                    os.environ['AWS_SECRET_ACCESS_KEY'] = credentials.secret_key
                    if credentials.token:
                        os.environ['AWS_SESSION_TOKEN'] = credentials.token
                if not os.environ.get('AWS_DEFAULT_REGION'):
                    os.environ['AWS_DEFAULT_REGION'] = self.region
        except Exception as e:
            log_exception(e)
    
    def _initialize_client(self):
        if self.client:
            return
        config = Config(
            endpoint_uri=f"https://bedrock-runtime.{self.region}.amazonaws.com",
            region=self.region,
            aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
            http_auth_scheme_resolver=HTTPAuthSchemeResolver(),
            http_auth_schemes={"aws.auth#sigv4": SigV4AuthScheme()}
        )
        self.client = BedrockRuntimeClient(config=config)
    
    async def send_event(self, event_json: str):
        try:
            if not self.stream or not self.stream.input_stream:
                return
            event = InvokeModelWithBidirectionalStreamInputChunk(
                value=BidirectionalInputPayloadPart(bytes_=event_json.encode('utf-8'))
            )
            if not self.stream.input_stream.closed:
                await self.stream.input_stream.send(event)
            else:
                print("[SONIC] Tried to send event but stream is closed")
        except Exception as e:
            log_exception(e)
    
    async def start_session(self):
        try:
            self._initialize_client()
            if not self.client:
                raise Exception("Failed to initialize Bedrock client")
            
            self.stream = await self.client.invoke_model_with_bidirectional_stream(
                InvokeModelWithBidirectionalStreamOperationInput(model_id=self.model_id)
            )
            self.is_active = True
            
            
            session_start = json.dumps({
                "event": {
                    "sessionStart": {
                        "inferenceConfiguration": {
                            "maxTokens": 150,  
                            "topP": 0.9,
                            "temperature": 0.8  
                        }
                    }
                }
            })
            await self.send_event(session_start)
            
            # Prompt start with audio output
            prompt_start = json.dumps({
                "event": {
                    "promptStart": {
                        "promptName": self.prompt_name,
                        "textOutputConfiguration": {"mediaType": "text/plain"},
                        "audioOutputConfiguration": {
                            "mediaType": "audio/lpcm",
                            "sampleRateHertz": OUTPUT_SAMPLE_RATE,
                            "sampleSizeBits": 16,
                            "channelCount": 1,
                            "voiceId": "matthew",
                            "encoding": "base64",
                            "audioType": "SPEECH"
                        }
                    }
                }
            })
            await self.send_event(prompt_start)
            
            # System content start
            text_content_start = json.dumps({
                "event": {
                    "contentStart": {
                        "promptName": self.prompt_name,
                        "contentName": self.content_name,
                        "type": "TEXT",
                        "interactive": True,
                        "role": "SYSTEM",
                        "textInputConfiguration": {"mediaType": "text/plain"}
                    }
                }
            })
            await self.send_event(text_content_start)
            
            # OPTIMIZED SYSTEM PROMPT - SHORT & FAST
            system_prompt = """You are Alan, a professional AI agent from Trianz helping with Health insurance Policy.

CRITICAL RULES:
1. ONE SHORT SENTENCE per response (max 15 words)
2. WAIT for user to finish speaking completely
3. RESPOND IMMEDIATELY when they stop
4. NEVER repeat questions
5. Be warm, natural, and conversational

GREETING (say this first):
"Hello! I'm Alan from Trianz. How can I help you with Health insurance today?"

Then STOP and WAIT.

QUESTIONS (ask ONE at a time, wait for answer):
1. "Are you looking for coverage for yourself or your family?"
2. "Do you currently have any Health insurance?"
3. "Would you like to hear about our Silver, Gold, or Platinum plans?"
4. " If user asks to explain the plan Silver, Gold, or Platinum plans, explain the plan in brief, whatever plan user asked to explain ?"
5. " If user asks for details about a specific plan than only share details "
6) " Once user finalise the plan than only go with the below flow of asking the personal details"
4. "What's your full name and date of birth?"
5. "Your phone number and email address?"
6. "Your home address and citizenship status?"
7. "Any major medical conditions or medications?"
8. "Do you smoke or drink regularly?"
9. "What's your occupation and annual income?"
10. "Who would be your primary beneficiary?"

UPLOAD DOCUMENTS:
- ONLY provide upload link when user EXPLICITLY asks for it
- User must say words like "upload", "link", or "where to upload"
- Make sure policy type (Silver/Gold/Platinum) is selected first
- If they ask for upload without selecting policy, remind them to choose a plan first
- Do NOT automatically offer upload link until they ask

KEY:
- ONE sentence only
- SHORT (under 20 words)
- WAIT for user
- NEVER repeat
- be empathetic 
- Respond FAST
- Upload link ONLY when explicitly requested
"""
            
            text_input = json.dumps({
                "event": {
                    "textInput": {
                        "promptName": self.prompt_name,
                        "contentName": self.content_name,
                        "content": system_prompt
                    }
                }
            })
            await self.send_event(text_input)
            
            text_content_end = json.dumps({
                "event": {
                    "contentEnd": {
                        "promptName": self.prompt_name,
                        "contentName": self.content_name
                    }
                }
            })
            await self.send_event(text_content_end)
            
            # Start response processing
            self.response = asyncio.create_task(self._process_responses())
            
            print(f"[NOVA] Session started successfully: {self.session_id}")
            
        except Exception as e:
            log_exception(e)
    
    async def start_audio_input(self):
        """Start audio input content block"""
        try:
            audio_content_start = json.dumps({
                "event": {
                    "contentStart": {
                        "promptName": self.prompt_name,
                        "contentName": self.audio_content_name,
                        "type": "AUDIO",
                        "interactive": True,
                        "role": "USER",
                        "audioInputConfiguration": {
                            "mediaType": "audio/lpcm",
                            "sampleRateHertz": INPUT_SAMPLE_RATE,
                            "sampleSizeBits": 16,
                            "channelCount": 1,
                            "audioType": "SPEECH",
                            "encoding": "base64"
                        }
                    }
                }
            })
            await self.send_event(audio_content_start)
            print(f"[AUDIO] Started audio input: {self.audio_content_name}")
        except Exception as e:
            log_exception(e)
    
    async def send_audio_chunk(self, audio_bytes: bytes):
        """Send audio chunk to Nova Sonic"""
        try:
            if not self.is_active:
                return
            blob = base64.b64encode(audio_bytes)
            audio_event = json.dumps({
                "event": {
                    "audioInput": {
                        "promptName": self.prompt_name,
                        "contentName": self.audio_content_name,
                        "content": blob.decode('utf-8')
                    }
                }
            })
            await self.send_event(audio_event)
        except Exception as e:
            log_exception(e)
    
    async def end_audio_input(self):
        """End audio input content block"""
        try:
            audio_content_end = json.dumps({
                "event": {
                    "contentEnd": {
                        "promptName": self.prompt_name,
                        "contentName": self.audio_content_name
                    }
                }
            })
            await self.send_event(audio_content_end)
            print(f"[AUDIO] Ended audio input: {self.audio_content_name}")
        except Exception as e:
            log_exception(e)
    
    async def _process_responses(self):
        try:
            if not self.stream:
                return
            
            audio_buffer = bytearray()
            
            while self.is_active:
                output = await self.stream.await_output()
                result = await output[1].receive()
                
                if result.value and result.value.bytes_:
                    response_data = result.value.bytes_.decode('utf-8')
                    json_data = json.loads(response_data)
                    
                    if 'event' in json_data:
                        if 'contentStart' in json_data['event']:
                            content_start = json_data['event']['contentStart']
                            self.role = content_start['role']
                            if 'additionalModelFields' in content_start:
                                add_fields = json.loads(content_start['additionalModelFields'])
                                self.display_assistant_text = add_fields.get('generationStage') == 'SPECULATIVE'
                            else:
                                self.display_assistant_text = False
                        
                        elif 'textOutput' in json_data['event']:
                            text = json_data['event']['textOutput']['content']
                            if self.role == "ASSISTANT" and self.display_assistant_text:
                                self.socketio.emit("assistant_message", {"text": text}, to=self.sid)
                                self.conversation.add_message('assistant', text)
                                
                                # STRICT: Only trigger upload if:
                                # 1. User explicitly asked for upload link
                                # 2. Policy type is selected
                                # Do NOT auto-trigger based on assistant's words
                            
                            elif self.role == "USER":
                                self.socketio.emit("user_message", {"text": text}, to=self.sid)
                                self.conversation.add_message('user', text)
                                
                                # Extract information and check for policy selection
                                policy_selected = self.conversation.extract_information(text)
                                if policy_selected:
                                    self.policy_type_confirmed = True
                                    print(f"[INFO] Policy type confirmed: {self.conversation.policy_info['policy_type']}")
                                
                                # Check if user is explicitly requesting upload
                                if self.conversation.check_upload_request(text):
                                    print(f"[INFO] User requested upload. Policy confirmed: {self.policy_type_confirmed}")
                                    if self.policy_type_confirmed:
                                        self.pending_upload_request = True
                                        print("[INFO] Upload request approved - policy type confirmed")
                                    else:
                                        # User asked for upload but no policy selected yet
                                        print("[WARNING] Upload requested but no policy type selected yet")
                                        self.socketio.emit("assistant_message", {
                                            "text": "Please select a policy type first (Silver, Gold, or Platinum) before uploading documents."
                                        }, to=self.sid)
                        
                        elif 'contentEnd' in json_data['event']:
                            # Send any buffered audio
                            if audio_buffer:
                                wav_bytes = pcm_to_wav_bytes(bytes(audio_buffer))
                                b64_wav = base64.b64encode(wav_bytes).decode('utf-8')
                                self.socketio.emit("audio_output", {"audio": b64_wav}, to=self.sid)
                                audio_buffer.clear()
                            
                            # STRICT: Only trigger upload after assistant finishes IF:
                            # 1. User explicitly requested upload
                            # 2. Policy type is confirmed
                            # 3. Upload not already triggered
                            if hasattr(self, 'role') and self.role == "ASSISTANT":
                                if (self.pending_upload_request and 
                                    self.policy_type_confirmed and 
                                    not self.upload_triggered):
                                    self.upload_triggered = True
                                    self.pending_upload_request = False
                                    print("[INFO] Triggering upload phase - all conditions met")
                                    asyncio.create_task(self._trigger_upload_phase())
                        
                        elif 'audioOutput' in json_data['event']:
                            audio_content = json_data['event']['audioOutput']['content']
                            audio_bytes = base64.b64decode(audio_content)
                            audio_buffer.extend(audio_bytes)
        
        except Exception as e:
            log_exception(e)
    
    async def _trigger_upload_phase(self):
        try:
            await self._save_conversation_to_s3()
            
            self.socketio.emit("upload_link", {"session_id": self.session_id}, to=self.sid)
            
            print(f"[NOVA] Upload phase triggered for session: {self.session_id}")
            
        except Exception as e:
            log_exception(e)
    
    async def _save_conversation_to_s3(self):
        try:
            import boto3
            import os
            region = os.environ.get('AWS_REGION', 'us-east-1')
            s3_client = boto3.client('s3', region_name=region)
            s3_bucket = 'nyl-underwriting-documents-121409194654'
            
            s3_key = f"{self.session_id}/conversation_context.json"
            
            conversation_data = self.conversation.to_dict()
            
            s3_client.put_object(
                Bucket=s3_bucket,
                Key=s3_key,
                Body=json.dumps(conversation_data, indent=2),
                ContentType='application/json',
                Metadata={
                    'session_id': self.session_id,
                    'data_type': 'trianz_underwriting_conversation',
                    'timestamp': datetime.now().isoformat()
                }
            )
            
            print(f"[S3] Conversation saved: s3://{s3_bucket}/{s3_key}")
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to save conversation to S3: {e}")
            return False
    
    async def end_session(self):
        try:
            if not self.is_active:
                return
            
            print(f"[NOVA] Ending session for: {self.session_id}")
            self.is_active = False
            
            if self.stream and self.stream.input_stream:
                try:
                    prompt_end = json.dumps({"event": {"promptEnd": {"promptName": self.prompt_name}}})
                    await self.send_event(prompt_end)
                    
                    session_end = json.dumps({"event": {"sessionEnd": {}}})
                    await self.send_event(session_end)
                    
                    await self.stream.input_stream.close()
                    print("[NOVA] Stream closed successfully")
                except Exception as e:
                    print(f"[NOVA] Error closing stream: {e}")
            
            self.stream = None
            self.client = None
            
            if hasattr(self, 'response') and self.response:
                self.response.cancel()
            
        except Exception as e:
            log_exception(e)


__all__ = ['NovaTrianzUnderwritingHandler', 'TrianzUnderwritingConversation']