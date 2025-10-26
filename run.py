from flask import Flask, request, render_template, jsonify, session, redirect, url_for, send_file
from flask_socketio import SocketIO, emit, join_room
import os
import json
import uuid
import zipfile
import boto3
import subprocess
import asyncio
import threading
from io import BytesIO
from flask_cors import CORS
from werkzeug.middleware.dispatcher import DispatcherMiddleware
import base64
from datetime import datetime
from werkzeug.exceptions import RequestEntityTooLarge, BadRequest
from botocore.exceptions import NoCredentialsError, ClientError
 
from nova_sonic_underwriting import NovaTrianzUnderwritingHandler
 
app = Flask(__name__, static_url_path='/flask-static', static_folder='static')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
CORS(app)
application = DispatcherMiddleware(Flask('dummy_app'), {'/flask': app})
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB
 
os.environ['AWS_ACCESS_KEY_ID'] = "Insert AWS CREDENTIALS"
os.environ['AWS_SECRET_ACCESS_KEY'] ="Insert AWS CREDENTIALS"
os.environ['AWS_REGION'] = "us-east-1"
 
S3_BUCKET = 'trianz-aws-hackathon'
AWS_REGION = 'us-east-1'
 
try:
    s3_client = boto3.client('s3', region_name=AWS_REGION)
    print(f"[INFO] S3 client initialized for bucket: {S3_BUCKET}")
except Exception as e:
    print(f"[ERROR] Failed to initialize S3 client: {e}")
    s3_client = None
 
ALLOWED_EXTENSIONS = {'zip'}
ALLOWED_MIME_TYPES = {'application/zip', 'application/x-zip-compressed'}
 
nova_underwriting_sessions = {}
 
loop = asyncio.new_event_loop()
def start_loop():
    asyncio.set_event_loop(loop)
    loop.run_forever()
threading.Thread(target=start_loop, daemon=True).start()
 
def generate_session_id():
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    unique_id = str(uuid.uuid4())[:8]
    return f"session_{timestamp}_{unique_id}"
 
def validate_zip_file(file):
    if not file:
        return False, "No file provided"
   
    if not file.filename:
        return False, "No file selected"
   
    if not file.filename.lower().endswith('.zip'):
        return False, "Only ZIP files are allowed. Please upload a .zip file."
   
    if hasattr(file, 'content_type') and file.content_type:
        if file.content_type not in ALLOWED_MIME_TYPES:
            return False, "Invalid file type detected. Please ensure you are uploading a valid ZIP file."
   
    if hasattr(file, 'content_length') and file.content_length:
        if file.content_length > 50 * 1024 * 1024:
            return False, "File size exceeds 50MB limit."
   
    return True, "Valid ZIP file"
 
def upload_to_s3(file, session_id, filename):
    try:
        if not s3_client:
            raise Exception("S3 client not initialized")
       
        file.seek(0)
        s3_key = f"{session_id}/{filename}"
       
        s3_client.upload_fileobj(
            file,
            S3_BUCKET,
            s3_key,
            ExtraArgs={
                'ContentType': 'application/zip',
                'Metadata': {
                    'session_id': session_id,
                    'upload_timestamp': datetime.now().isoformat(),
                    'original_filename': filename
                }
            }
        )
       
        print(f"[SUCCESS] File uploaded to S3: s3://{S3_BUCKET}/{s3_key}")
        return True, s3_key
       
    except Exception as e:
        print(f"[ERROR] S3 upload failed: {e}")
        return False, str(e)
 
def trigger_agentcore_processing(session_id, s3_key):
    try:
        agentcore_payload = {
            "request_type": "s3_process",
            "s3_bucket": S3_BUCKET,
            "s3_key": s3_key,
            "session_id": session_id
        }
       
        payload_json = json.dumps(agentcore_payload)
        command = ['agentcore', 'invoke', payload_json]
       
        print(f"[INFO] Triggering AgentCore: {' '.join(command)}")
        print(f"[DEBUG] Full payload: {payload_json}")
       
        def run_agentcore():
            try:
                print(f"[DEBUG] Starting agentcore process...")
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=1800
                )
               
                print(f"[DEBUG] AgentCore return code: {result.returncode}")
                print(f"[DEBUG] STDOUT: {result.stdout}")
                print(f"[DEBUG] STDERR: {result.stderr}")
               
                if result.returncode == 0:
                    print(f"[SUCCESS] AgentCore processing completed for session: {session_id}")
                    socketio.emit('agentcore_complete', {
                        'session_id': session_id,
                        'status': 'completed',
                        'message': 'AgentCore processing completed successfully'
                    })
                else:
                    print(f"[ERROR] AgentCore processing failed: {result.stderr}")
                    socketio.emit('agentcore_error', {
                        'session_id': session_id,
                        'status': 'failed',
                        'error': result.stderr
                    })
                   
            except subprocess.TimeoutExpired:
                print(f"[ERROR] AgentCore processing timed out for session: {session_id}")
                socketio.emit('agentcore_error', {
                    'session_id': session_id,
                    'status': 'timeout',
                    'error': 'Processing timed out after 30 minutes'
                })
            except Exception as e:
                print(f"[ERROR] AgentCore execution error: {e}")
                import traceback
                traceback.print_exc()
                socketio.emit('agentcore_error', {
                    'session_id': session_id,
                    'status': 'error',
                    'error': str(e)
                })
       
        thread = threading.Thread(target=run_agentcore)
        thread.daemon = True
        thread.start()
       
        return True
       
    except Exception as e:
        print(f"[ERROR] Failed to trigger AgentCore: {e}")
        import traceback
        traceback.print_exc()
        return False
 
def read_agent_status_from_s3(session_id):
    try:
        if not s3_client:
            raise Exception("S3 client not initialized")
       
        s3_key = f"{session_id}/agent_status.json"
        response = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
        status_data = json.loads(response['Body'].read().decode('utf-8'))
        return status_data
       
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            return {
                'session_id': session_id,
                'status': 'initializing',
                'agents': {
                    'data_intake': {'status': 'pending', 'analysis': '', 'timestamp': ''},
                    'document_verification': {'status': 'pending', 'analysis': '', 'timestamp': ''},
                    'medical_risk_assessment': {'status': 'pending', 'analysis': '', 'timestamp': ''},
                    'financial': {'status': 'pending', 'analysis': '', 'timestamp': ''},
                    'driving': {'status': 'pending', 'analysis': '', 'timestamp': ''},
                    'compliance': {'status': 'pending', 'analysis': '', 'timestamp': ''},
                    'lifestyle_behavioral': {'status': 'pending', 'analysis': '', 'timestamp': ''},
                    'summary_generation': {'status': 'pending', 'analysis': '', 'timestamp': ''}
                }
            }
        else:
            raise e
 
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        next_page = request.form.get('next', url_for('index_new'))
 
        if username == 'demo_trianz' and password == 'Demo@#123':
            session['logged_in'] = True
            return redirect(next_page)  
        else:
            error = 'Invalid username or password'
            return render_template('login.html', error=error)
 
    # Get the next parameter from URL
    next_page = request.args.get('next', url_for('index_new'))
    return render_template('login.html', next=next_page)
 
 
# Add new route for modern UI
@app.route('/new')
def index_new():
    if 'logged_in' not in session or not session['logged_in']:
        return redirect(url_for('login', next=url_for('index_new')))
    return render_template('index-new.html')
 
# Keep original route unchanged
@app.route('/', methods=['GET', 'POST'])
def index():
    if 'logged_in' not in session or not session['logged_in']:
        return redirect(url_for('login'))  
 
    if request.method == 'POST':
        try:
           
            if 'zipFileInput' not in request.files:
                return render_template('index.html', error='No file uploaded. Please select a ZIP file.')
            file = request.files['zipFileInput']
         
            is_valid, message = validate_zip_file(file)
            if not is_valid:
                return render_template('index.html', error=message)
            print(f"[INFO] File validation successful: {message}")
           
            session_id = generate_session_id()
            original_filename = file.filename
            safe_filename = f"{session_id}_upload.zip"
            print(f"[INFO] Generated session ID: {session_id}")
           
            upload_success, s3_result = upload_to_s3(file, session_id, safe_filename)
            if not upload_success:
                return render_template('index.html',
                                     error=f'Failed to upload file to S3: {s3_result}')
            s3_key = s3_result
            print(f"[INFO] File uploaded to S3: {s3_key}")
           
            socketio.emit('upload_complete', {
                'session_id': session_id,
                's3_key': s3_key,
                'message': 'File uploaded to S3 successfully'
            })
           
            trigger_success = trigger_agentcore_processing(session_id, s3_key)
            if not trigger_success:
                return render_template('index.html',
                                     error='File uploaded but failed to start processing')
           
            socketio.emit('processing_started', {
                'session_id': session_id,
                'message': 'AgentCore processing started...'
            })
           
            monitor_thread = threading.Thread(target=monitor_s3_agent_status, args=(session_id,))
            monitor_thread.daemon = True
            monitor_thread.start()
           
            return render_template('index.html',
                                 processing=True,
                                 session_id=session_id,
                                 s3_key=s3_key)
        except Exception as e:
            error_message = f"Request processing failed: {str(e)}"
            print(f"[ERROR] {error_message}")
            return render_template('index.html', error=error_message)
 
   
    return render_template('index.html')
 
 
@app.route('/upload/<session_id>', methods=['GET', 'POST'])
def upload_from_nova(session_id):
    try:
        if request.method == 'GET':
            return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Trianz Document Upload</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
        .container {{ border: 1px solid #ddd; border-radius: 8px; padding: 30px; background: #f8f9fa; }}
        .upload-area {{ border: 2px dashed #007bff; border-radius: 8px; padding: 40px; text-align: center; margin: 20px 0; background: white; }}
        button {{ background-color: #007bff; color: white; border: none; padding: 12px 24px; border-radius: 4px; cursor: pointer; font-size: 16px; }}
        button:hover {{ background-color: #0056b3; }}
        .success {{ color: green; font-weight: bold; }}
        .error {{ color: red; font-weight: bold; }}
        h2 {{ color: #007bff; margin-bottom: 20px; }}
        ul {{ text-align: left; }}
    </style>
</head>
<body>
    <div class="container">
        <h2>Trianz Underwriting - Document Upload</h2>
        <p><strong>Session:</strong> {session_id}</p>
        <p>Upload your documents as a single ZIP file:</p>
        <ul>
            <li>Medical records and physician statements</li>
            <li>Driving record (MVR)</li>
            <li>Financial verification (tax returns, pay stubs, bank statements)</li>
            <li>Identity verification (driver's license, SSN card)</li>
            <li>Completed application form</li>
        </ul>
       
        <form action="/upload/{session_id}" method="post" enctype="multipart/form-data">
            <div class="upload-area">
                <input type="file" name="zipFileInput" accept=".zip" required style="margin-bottom: 20px;">
                <br>
                <button type="submit">Upload Documents</button>
            </div>
        </form>
       
        <div id="status"></div>
    </div>
</body>
</html>
"""
       
        if 'zipFileInput' not in request.files:
            return "<div class='error'>No file selected</div>", 400
       
        file = request.files['zipFileInput']
        if not file or file.filename == '':
            return "<div class='error'>No file selected</div>", 400
       
        is_valid, message = validate_zip_file(file)
        if not is_valid:
            return f"<div class='error'>{message}</div>", 400
       
        safe_filename = f"{session_id}_trianz_upload.zip"
        upload_success, upload_result = upload_to_s3(file, session_id, safe_filename)
       
        if upload_success:
            s3_key = upload_result
            print(f"[SUCCESS] Nova Sonic session {session_id}: Uploaded to S3")
           
            socketio.emit('nova_upload_complete', {
                'session_id': session_id,
                's3_key': s3_key,
                'message': 'File uploaded successfully'
            })
           
            trigger_agentcore_processing(session_id, s3_key)
           
            monitor_thread = threading.Thread(target=monitor_s3_agent_status, args=(session_id,))
            monitor_thread.daemon = True
            monitor_thread.start()
           
            return f"<div class='success'>Uploaded successfully! Processing started. You may close this window.</div>"
        else:
            return f"<div class='error'>Upload failed: {upload_result}</div>", 400
           
    except Exception as e:
        print(f"[ERROR] Upload error: {e}")
        return "<div class='error'>Internal server error during file upload.</div>", 500
 
@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'Policy Generation & Underwriting System with Nova Sonic',
        'version': '3.0.0',
        's3_bucket': S3_BUCKET,
        's3_status': 'connected' if s3_client else 'disconnected',
        'nova_sonic': 'enabled'
    })
 
 
@app.route('/status/<session_id>')
def get_status(session_id):
    try:
        status_data = read_agent_status_from_s3(session_id)
        agents_status = status_data.get('agents', {})
        overall_status = status_data.get('status', 'initializing')
       
        if agents_status:
            agent_statuses = [agent.get('status', 'pending') for agent in agents_status.values()]
            if all(status == 'completed' for status in agent_statuses):
                overall_status = 'completed'
            elif any(status == 'failed' for status in agent_statuses):
                overall_status = 'failed'
            elif any(status == 'in_progress' for status in agent_statuses):
                overall_status = 'in_progress'
       
        return jsonify({
            'status': overall_status,
            'agents': agents_status,
            'session_id': session_id,
            's3_location': f"s3://{S3_BUCKET}/{session_id}/agent_status.json"
        })
       
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': f'Failed to retrieve status: {str(e)}',
            'agents': {}
        }), 500
 
@app.route('/view_policy/<session_id>')
def view_policy(session_id):
    """View policy PDF inline in browser"""
    try:
        print(f"[DEBUG] View policy requested for session: {session_id}")
        s3_key = f"{session_id}/agent_status.json"
       
        try:
            response = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
            agent_status = json.loads(response['Body'].read().decode('utf-8'))
        except Exception as e:
            return jsonify({
                'status': 'error',
                'error': f'Could not read session data: {str(e)}'
            }), 404
       
        policy_info = agent_status.get('policy_generated', {})
       
        if not policy_info or policy_info.get('status') != 'completed':
            return jsonify({
                'status': 'error',
                'error': 'Policy document not yet generated for this session'
            }), 404
       
        s3_location = policy_info.get('s3_location', '')
        if not s3_location:
            return jsonify({
                'status': 'error',
                'error': 'Policy S3 location not found'
            }), 404
       
        s3_policy_key = s3_location.replace(f's3://{S3_BUCKET}/', '')
       
        try:
            response = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_policy_key)
            policy_data = response['Body'].read()
           
            filename = policy_info.get('local_file', f'policy_{session_id}.pdf')
           
            # Return PDF for inline viewing in browser
            return send_file(
                BytesIO(policy_data),
                mimetype='application/pdf',
                as_attachment=False,  # ← Display inline in browser
                download_name=filename
            )
           
        except Exception as e:
            return jsonify({
                'status': 'error',
                'error': f'Failed to retrieve policy from S3: {str(e)}'
            }), 500
       
    except Exception as e:
        print(f"[ERROR] Policy view error: {e}")
        return jsonify({
            'status': 'error',
            'error': f'Failed to view policy: {str(e)}'
        }), 500
 
@app.route('/download_policy/<session_id>')
def download_policy(session_id):
    """Download policy PDF file - searches for any policy PDF in session folder"""
    try:
        print(f"[DEBUG] Download policy requested for session: {session_id}")
       
       
        prefix = f"{session_id}/policy_generated_"
       
        try:
            print(f"[DEBUG] Searching S3 for policies with prefix: {prefix}")
            response = s3_client.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
           
            if 'Contents' not in response or len(response['Contents']) == 0:
                print(f"[ERROR] No policy files found with prefix: {prefix}")
                return jsonify({
                    'status': 'error',
                    'error': 'Policy document not found in S3. Please wait for policy generation to complete.'
                }), 404
           
            # Get all PDF files
            policy_objects = [obj for obj in response['Contents'] if obj['Key'].endswith('.pdf')]
           
            if not policy_objects:
                print(f"[ERROR] No PDF files found in search results")
                return jsonify({
                    'status': 'error',
                    'error': 'No policy PDF found in session folder.'
                }), 404
           
           
            policy_objects.sort(key=lambda x: x['LastModified'], reverse=True)
            s3_policy_key = policy_objects[0]['Key']
           
            print(f"[DEBUG] Found policy at: {s3_policy_key}")
           
           
            policy_response = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_policy_key)
            policy_data = policy_response['Body'].read()
           
            filename = f"policy_{session_id}.pdf"
           
            print(f"[SUCCESS] Sending policy file: {filename}, size: {len(policy_data)} bytes")
           
           
            return send_file(
                BytesIO(policy_data),
                mimetype='application/pdf',
                as_attachment=True,
                download_name=filename
            )
           
        except ClientError as e:
            error_code = e.response['Error']['Code']
            print(f"[ERROR] S3 ClientError: {error_code}")
            if error_code == 'NoSuchKey':
                return jsonify({
                    'status': 'error',
                    'error': 'Policy not found in S3.'
                }), 404
            else:
                return jsonify({
                    'status': 'error',
                    'error': f'S3 error: {str(e)}'
                }), 500
               
        except Exception as e:
            print(f"[ERROR] Failed to find/download policy from S3: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'status': 'error',
                'error': f'Failed to download policy from S3: {str(e)}'
            }), 500
       
    except Exception as e:
        print(f"[ERROR] Policy download error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'status': 'error',
            'error': f'Failed to download policy: {str(e)}'
        }), 500
 
 
@app.route('/policy_status/<session_id>')
def policy_status(session_id):
    try:
        print(f"[DEBUG] Policy status requested for session: {session_id}")
        s3_key = f"{session_id}/agent_status.json"
       
        try:
            response = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
            agent_status = json.loads(response['Body'].read().decode('utf-8'))
        except Exception as e:
            return jsonify({
                'status': 'error',
                'error': f'Session not found: {str(e)}'
            }), 404
       
        policy_info = agent_status.get('policy_generated', {})
       
        return jsonify({
            'status': 'success',
            'session_id': session_id,
            'policy_generated': policy_info.get('status') == 'completed',
            'policy_info': policy_info,
            's3_location': policy_info.get('s3_location', ''),
            'timestamp': policy_info.get('timestamp', '')
        })
       
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500
 
@socketio.on('connect')
def handle_connect():
    print(f"[SOCKET] Client connected: {request.sid}")
    emit('status', {'message': 'Connected to Underwriting with Nova Sonic'})
 
@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    print(f"[SOCKET] Client disconnected: {sid}")
   
    if sid in nova_underwriting_sessions:
        handler = nova_underwriting_sessions[sid]
        if handler.is_active:
            asyncio.run_coroutine_threadsafe(handler.end_session(), loop)
        del nova_underwriting_sessions[sid]
 
@socketio.on('join_session')
def handle_join_session(data):
    session_id = data.get('session_id')
    if session_id:
        join_room(session_id)
        print(f"[SOCKET] Client {request.sid} joined session {session_id}")
 
@socketio.on('start_nova_session')
def on_start_nova_session():
    sid = request.sid
   
    handler = NovaTrianzUnderwritingHandler(sid, socketio)
    nova_underwriting_sessions[sid] = handler
   
    print(f"[NOVA] Starting underwriting session for {sid} with session_id: {handler.session_id}")
   
    asyncio.run_coroutine_threadsafe(handler.start_session(), loop)
   
    emit('nova_session_started', {'session_id': handler.session_id}, to=sid)
 
@socketio.on('start_recording')
def on_start_recording():
    sid = request.sid
    handler = nova_underwriting_sessions.get(sid)
    if handler:
        asyncio.run_coroutine_threadsafe(handler.start_audio_input(), loop)
        emit('recording_started', to=sid)
 
@socketio.on('audio_data')
def on_audio_data(data):
    sid = request.sid
    handler = nova_underwriting_sessions.get(sid)
    if handler:
        audio_b64 = data.get('audio', '')
        try:
            audio_bytes = base64.b64decode(audio_b64)
            asyncio.run_coroutine_threadsafe(handler.send_audio_chunk(audio_bytes), loop)
        except Exception as e:
            print(f"[ERROR] Audio data error: {e}")
 
@socketio.on('stop_recording')
def on_stop_recording():
    sid = request.sid
    handler = nova_underwriting_sessions.get(sid)
    if handler:
        asyncio.run_coroutine_threadsafe(handler.end_audio_input(), loop)
        emit('recording_stopped', to=sid)
 
@socketio.on('end_nova_session')
def on_end_nova_session():
    sid = request.sid
    handler = nova_underwriting_sessions.get(sid)
    if handler:
        asyncio.run_coroutine_threadsafe(handler.end_session(), loop)
        emit('nova_session_stopped', to=sid)
 
def monitor_s3_agent_status(session_id, duration=1800):
    last_status = {}
    start_time = datetime.now().timestamp()
   
    print(f"[MONITOR] Started monitoring S3 status for session: {session_id}")
   
    while datetime.now().timestamp() - start_time < duration:
        try:
            current_status = read_agent_status_from_s3(session_id)
            current_agents = current_status.get('agents', {})
           
            for agent_name, agent_data in current_agents.items():
                agent_status = agent_data.get('status', 'pending')
               
                if agent_name not in last_status or last_status[agent_name].get('status') != agent_status:
                    socketio.emit('agent_status_update', {
                        'session_id': session_id,
                        'agent': agent_name,
                        'status': agent_status,
                        'data': agent_data,
                        'timestamp': agent_data.get('timestamp', ''),
                        'analysis': agent_data.get('analysis', '')
                    })
                    print(f"[SOCKET] Status update for {agent_name}: {agent_status}")
           
            last_status = current_agents.copy()
           
            overall_status = current_status.get('status', 'in_progress')
            if overall_status == 'completed':
                policy_info = current_status.get('policy_generated', {})
               
                socketio.emit('processing_complete', {
                    'session_id': session_id,
                    'status': 'completed',
                    'final_summary': current_status.get('final_summary', ''),
                    's3_location': f"s3://{S3_BUCKET}/{session_id}/",
                    'policy_generated': policy_info.get('status') == 'completed',
                    'policy_s3_key': policy_info.get('s3_location', '').replace(f's3://{S3_BUCKET}/', '') if policy_info.get('s3_location') else None
                })
                print(f"[SOCKET] Processing complete for session {session_id}")
               
                if policy_info.get('status') == 'completed':
                    socketio.emit('policy_generated', {
                        'session_id': session_id,
                        'policy_number': policy_info.get('policy_number', 'N/A'),
                        's3_location': policy_info.get('s3_location', ''),
                        'download_url': f'/download_policy/{session_id}'
                    })
                    print(f"[SOCKET] Policy generated for session {session_id}")
               
                break
            elif overall_status == 'failed':
                socketio.emit('processing_failed', {
                    'session_id': session_id,
                    'status': 'failed'
                })
                print(f"[SOCKET] Processing failed for session {session_id}")
                break
               
        except Exception as e:
            print(f"[ERROR] Error monitoring S3 status: {e}")
       
        import time
        time.sleep(5)
   
    print(f"[MONITOR] Stopped monitoring session: {session_id}")
 
@app.errorhandler(413)
def file_too_large(e):
    return render_template('index.html', error='File size exceeds 50MB limit.'), 413
 
@app.errorhandler(400)
def bad_request(e):
    return render_template('index.html', error='Invalid request.'), 400
 
@app.errorhandler(500)
def internal_error(e):
    print(f"[ERROR] Internal server error: {str(e)}")
    return render_template('index.html', error='Internal server error.'), 500
 
if __name__ == '__main__':
    import os
    if not os.environ.get('AWS_REGION'):
        os.environ['AWS_REGION'] = 'us-east-1'
   
    if not os.environ.get('AWS_DEFAULT_REGION'):
        os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
   
    print("=" * 60)
    print("NOVA SONIC VOICE INTEGRATION policy generation")
    print("=" * 60)
    print(f"[INFO] AWS Region configured: {os.environ.get('AWS_REGION')}")
    print(f"[INFO] S3 Bucket: {S3_BUCKET}")
   
    if s3_client:
        try:
            s3_client.head_bucket(Bucket=S3_BUCKET)
            print(f"[SUCCESS] S3 bucket accessible: {S3_BUCKET}")
        except Exception as e:
            print(f"[WARNING] S3 bucket access issue: {e}")
    else:
        print("[ERROR] S3 client not initialized")
   
    print("=" * 60)
    print("[INFO] Starting Flask-SocketIO with Nova Sonic integration")
    print("[INFO] Access: http://127.0.0.1:8002")
    print("[INFO] Health check: http://127.0.0.1:8002/health")
    print("=" * 60)
   
    socketio.run(
        app,
        debug=False,
        host='0.0.0.0',
        port=8002,
        allow_unsafe_werkzeug=True
    )
 