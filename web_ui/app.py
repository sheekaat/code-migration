"""
Web UI for Code Migration Platform
Lightweight Flask-based interface for ZIP upload and conversion.
Does not disturb existing core logic.
"""

from __future__ import annotations
import os
import sys
import zipfile
import tempfile
import shutil
import threading
import logging
import json
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from queue import Queue

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.models import TargetLanguage
from shared.config import get_logger, load_config
from orchestration.pipeline import MigrationOrchestrator

log = get_logger(__name__)
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file size

# Global state for progress tracking
progress_queues: dict[str, Queue] = {}


class QueueLogHandler(logging.Handler):
    """Sends log records to UI queue."""
    
    def __init__(self, queue: Queue):
        super().__init__()
        self.queue = queue
        
    def emit(self, record):
        try:
            msg = self.format(record)
            self.queue.put({
                'timestamp': datetime.now().isoformat(),
                'message': msg,
                'type': 'info'
            })
        except Exception:
            self.handleError(record)


class ProgressCapture:
    """Captures stdout output and sends to UI via queue."""
    
    def __init__(self, queue: Queue):
        self.queue = queue
        
    def write(self, message: str):
        if message.strip():
            self.queue.put({
                'timestamp': datetime.now().isoformat(),
                'message': message.strip(),
                'type': 'info'
            })
            
    def flush(self):
        pass


def run_migration(repo_path: str, target: str, job_id: str):
    """Run migration in background thread with progress capture."""
    log_handler = None
    try:
        queue = progress_queues.get(job_id)
        if queue:
            queue.put({'type': 'status', 'status': 'running', 'message': 'Starting migration...'})
        
        # Setup logging handler to capture all logs (only once per job)
        if queue:
            log_handler = QueueLogHandler(queue)
            log_handler.setFormatter(logging.Formatter('%(name)s: %(message)s'))
            # Add ONLY to root logger - child loggers will propagate up
            root_logger = logging.getLogger()
            if not any(isinstance(h, QueueLogHandler) for h in root_logger.handlers):
                root_logger.addHandler(log_handler)
                log.info("Added QueueLogHandler to root logger")
            # Note: Don't add to specific loggers - they propagate to root!
        
        # Create orchestrator and run
        config = load_config()
        orchestrator = MigrationOrchestrator(config)
        
        target_enum = TargetLanguage(target.lower())
        result_dir = orchestrator.run(repo_path, target_language=target_enum)
        
        if queue:
            queue.put({
                'type': 'complete',
                'status': 'success',
                'output_dir': result_dir,
                'message': f'Migration complete! Output: {result_dir}'
            })
            
    except Exception as e:
        log.error("Migration failed: %s", e)
        if queue:
            queue.put({
                'type': 'error',
                'status': 'failed',
                'message': str(e)
            })
    finally:
        # Clean up log handler from root logger only
        if log_handler:
            root_logger = logging.getLogger()
            if log_handler in root_logger.handlers:
                root_logger.removeHandler(log_handler)
                log.info("Removed QueueLogHandler from root logger")


@app.route('/')
def index():
    """Main UI page."""
    targets = [
        {'value': 'java_spring', 'label': 'Java Spring Boot'},
        {'value': 'react_js', 'label': 'ReactJS / TypeScript'}
    ]
    return render_template('index.html', targets=targets)


@app.route('/api/upload', methods=['POST'])
def upload():
    """Handle ZIP upload and extract."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not file.filename.endswith('.zip'):
        return jsonify({'error': 'Only ZIP files are supported'}), 400
    
    try:
        # Create temp directory
        temp_dir = tempfile.mkdtemp(prefix='migration_upload_')
        zip_path = Path(temp_dir) / 'upload.zip'
        
        # Save uploaded file
        file.save(zip_path)
        
        # Extract
        extract_dir = Path(temp_dir) / 'source'
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(extract_dir)
        
        # Clean up zip
        zip_path.unlink()
        
        # Find the actual source folder (handle nested zips)
        source_path = extract_dir
        items = list(extract_dir.iterdir())
        if len(items) == 1 and items[0].is_dir():
            source_path = items[0]
        
        return jsonify({
            'success': True,
            'job_id': Path(temp_dir).name,
            'source_path': str(source_path),
            'temp_dir': temp_dir,
            'message': f'Uploaded and extracted: {file.filename}'
        })
        
    except Exception as e:
        log.error("Upload failed: %s", e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/convert', methods=['POST'])
def convert():
    """Start conversion job."""
    data = request.json
    source_path = data.get('source_path')
    target = data.get('target')
    job_id = data.get('job_id')
    
    if not all([source_path, target, job_id]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    if target not in ['java_spring', 'react_js']:
        return jsonify({'error': 'Invalid target language'}), 400
    
    # Create progress queue
    queue = Queue()
    progress_queues[job_id] = queue
    
    # Start migration in background thread
    thread = threading.Thread(
        target=run_migration,
        args=(source_path, target, job_id)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'success': True,
        'job_id': job_id,
        'message': 'Conversion started'
    })


@app.route('/api/progress/<job_id>')
def progress(job_id):
    """Stream progress updates via SSE."""
    def event_stream():
        queue = progress_queues.get(job_id)
        if not queue:
            yield f'data: {json.dumps({"type": "error", "message": "Job not found"})}\n\n'
            return
        
        # Send initial connected message
        yield f'data: {json.dumps({"type": "status", "message": "Connected to progress stream"})}\n\n'
        
        while True:
            try:
                message = queue.get(timeout=30)
                yield f'data: {json.dumps(message)}\n\n'
                
                if message.get('type') in ['complete', 'error']:
                    break
                    
            except:
                # Timeout - send heartbeat
                yield f'data: {json.dumps({"type": "heartbeat"})}\n\n'
    
    return Response(
        stream_with_context(event_stream()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )


@app.route('/api/download/<job_id>')
def download(job_id):
    """Download converted output as ZIP."""
    # Find output directory
    temp_dir = Path(tempfile.gettempdir()) / job_id
    source_path = temp_dir / 'source'
    
    # Look for migration output
    output_dirs = list(Path('output').glob(f'migration_*'))
    if output_dirs:
        latest = max(output_dirs, key=lambda p: p.stat().st_mtime)
        
        # Create zip of output
        zip_path = temp_dir / 'converted.zip'
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
            for file_path in latest.rglob('*'):
                if file_path.is_file():
                    z.write(file_path, file_path.relative_to(latest))
        
        return Response(
            zip_path.read_bytes(),
            mimetype='application/zip',
            headers={
                'Content-Disposition': f'attachment; filename=converted_{target}.zip'
            }
        )
    
    return jsonify({'error': 'Output not found'}), 404


def cleanup_old_uploads():
    """Remove uploads older than 24 hours."""
    temp_dir = Path(tempfile.gettempdir())
    for item in temp_dir.glob('migration_upload_*'):
        if item.is_dir():
            age = datetime.now().timestamp() - item.stat().st_mtime
            if age > 86400:  # 24 hours
                shutil.rmtree(item, ignore_errors=True)


if __name__ == '__main__':
    # Clean up old uploads on startup
    cleanup_old_uploads()
    
    # Run Flask
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
