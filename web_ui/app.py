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
from conversion.streaming_pipeline import StreamingConversionPipeline
from ingestion.crawler import RepoCrawler
from analysis.engine import analyse
from validation.runner import ValidationRunner
from output.generator import OutputGenerator
from pathlib import Path

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


def run_migration(repo_path: str, target: str, job_id: str, use_streaming: bool = True, skip_patterns: list = None):
    """Run migration in background thread with progress capture.
    
    Uses streaming mode for large repos to save memory.
    """
    skip_patterns = skip_patterns or []
    log_handler = None
    try:
        queue = progress_queues.get(job_id)
        if queue:
            queue.put({'type': 'status', 'status': 'running', 'message': 'Starting migration...'})
        
        # Setup logging handler to capture all logs (only once per job)
        if queue:
            log_handler = QueueLogHandler(queue)
            log_handler.setFormatter(logging.Formatter('%(name)s: %(message)s'))
            root_logger = logging.getLogger()
            if not any(isinstance(h, QueueLogHandler) for h in root_logger.handlers):
                root_logger.addHandler(log_handler)
        
        # Load config and setup
        config = load_config()
        # Force fast model and disable accuracy loop
        config['llm'] = config.get('llm', {})
        config['llm']['model'] = 'gemini-2.5-flash'
        config['llm']['chunk_size'] = 400  # Large chunks to avoid splitting files
        config['accuracy'] = {'enabled': False}
        target_enum = TargetLanguage(target.lower())
        output_base = Path(__file__).parent.parent / 'output'
        output_base.mkdir(parents=True, exist_ok=True)
        
        # Determine if we should use streaming (for large repos or always)
        repo_path_obj = Path(repo_path)
        file_count = len(list(repo_path_obj.rglob('*')))
        log.info(f"Repository has {file_count} items, using {'streaming' if use_streaming else 'batch'} mode")
        
        if use_streaming:
            result_dir = _run_streaming_migration(
                repo_path, target_enum, config, output_base, queue, job_id, skip_patterns
            )
        else:
            orchestrator = MigrationOrchestrator(config)
            result_dir = orchestrator.run(repo_path, target_language=target_enum, skip_patterns=skip_patterns)
        
        if queue:
            queue.put({
                'type': 'complete',
                'status': 'success',
                'output_dir': str(result_dir),
                'message': f'Migration complete! Output: {result_dir}'
            })
            
    except Exception as e:
        log.error("Migration failed: %s", e)
        import traceback
        log.error(traceback.format_exc())
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


def _run_streaming_migration(repo_path, target_enum, config, output_base, queue, job_id, skip_patterns=None):
    """Run streaming migration for memory efficiency."""
    from accuracy.loop import SelfHealingAccuracyLoop
    
    skip_patterns = skip_patterns or []
    
    # Layer 1: Ingestion
    log.info("[1/6] Ingesting repository...")
    if skip_patterns:
        log.info(f"  Skip patterns: {skip_patterns}")
    if queue:
        queue.put({'type': 'status', 'message': '[1/6] Ingesting repository...'})
    
    crawler = RepoCrawler(repo_path, target_language=target_enum, skip_patterns=skip_patterns)
    manifest = crawler.crawl()
    log.info(f"  Found {len(manifest.files)} files")
    
    # Layer 2: Analysis
    log.info("[2/6] Running analysis engine...")
    if queue:
        queue.put({'type': 'status', 'message': '[2/6] Analyzing files...'})
    
    manifest = analyse(manifest, config)
    green = sum(1 for f in manifest.files if f.complexity_tier.value == 'green')
    amber = sum(1 for f in manifest.files if f.complexity_tier.value == 'amber')
    red = sum(1 for f in manifest.files if f.complexity_tier.value == 'red')
    log.info(f"  Tiers: green={green}, amber={amber}, red={red}")
    
    # Layer 3: Streaming Conversion
    log.info("[3/6] Running streaming conversion pipeline...")
    if queue:
        queue.put({'type': 'status', 'message': '[3/6] Converting files (streaming)...'})
    
    streaming_pipeline = StreamingConversionPipeline(config)
    output_dir = output_base / f'migration_{job_id}'
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Convert files one at a time
    results = []
    for result in streaming_pipeline.convert_manifest_streaming(manifest, output_dir):
        results.append(result)
        if queue and result.source_file:
            status = "✓" if result.confidence >= 0.75 else "⚠"
            queue.put({
                'type': 'info',
                'message': f"  {status} Converted: {result.source_file.path} (conf={result.confidence:.2f})"
            })
    
    manifest.conversion_results = results
    manifest.stats["conversion"] = streaming_pipeline.get_stats()
    
    # Layer 4: Validation (file by file)
    log.info("[4/6] Running validation...")
    if queue:
        queue.put({'type': 'status', 'message': '[4/6] Validating conversions...'})
    
    validator = ValidationRunner(config)
    reports = validator.validate_manifest(manifest)
    passed = sum(1 for r in reports if r.overall_passed)
    log.info(f"  Validation: {passed}/{len(reports)} passed")
    
    # Layer 5: Accuracy Loop (for files that need improvement)
    if config.get('accuracy', {}).get('enabled', False):
        log.info("[5/6] Running accuracy improvements...")
        if queue:
            queue.put({'type': 'status', 'message': '[5/6] Improving accuracy...'})
        
        accuracy_loop = SelfHealingAccuracyLoop(config)
        accuracy_stats = accuracy_loop.run_for_manifest(manifest)
        log.info(f"  Accuracy: {accuracy_stats.get('pass_rate', '0%')} pass rate")
    
    # Layer 6: Generate final report
    log.info("[6/6] Generating output report...")
    if queue:
        queue.put({'type': 'status', 'message': '[6/6] Generating output report...'})
    
    generator = OutputGenerator(config)
    result_dir = generator.generate(manifest, reports)
    
    return result_dir


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
    """Handle ZIP upload and extract to input/ folder."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not file.filename.endswith('.zip'):
        return jsonify({'error': 'Only ZIP files are supported'}), 400
    
    try:
        # Define input folder (relative to project root)
        input_dir = Path(__file__).parent.parent / 'input'
        
        # Clear existing input folder contents
        if input_dir.exists():
            for item in input_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink()
            log.info("Cleared existing input folder")
        else:
            input_dir.mkdir(parents=True, exist_ok=True)
        
        # Save uploaded file
        zip_path = input_dir / 'upload.zip'
        file.save(zip_path)
        
        # Extract to input folder
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(input_dir)
        
        # Clean up zip
        zip_path.unlink()
        
        # Find the actual source folder (handle nested zips)
        source_path = input_dir
        items = [i for i in input_dir.iterdir() if i.is_dir()]
        if len(items) == 1:
            source_path = items[0]
        
        return jsonify({
            'success': True,
            'job_id': f'job_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
            'source_path': str(source_path),
            'input_dir': str(input_dir),
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
    skip_patterns = data.get('skip_patterns', [])
    
    log.info(f"[CONVERT] Received skip_patterns: {skip_patterns}")
    
    if not all([source_path, target, job_id]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    if target not in ['java_spring', 'react_js']:
        return jsonify({'error': 'Invalid target language'}), 400
    
    # Clear output folder (keep Python files)
    clear_output_folder()
    
    # Create progress queue
    queue = Queue()
    progress_queues[job_id] = queue
    
    # Start migration in background thread
    log.info(f"[CONVERT] Starting thread with skip_patterns: {skip_patterns}")
    thread = threading.Thread(
        target=run_migration,
        args=(source_path, target, job_id, True, skip_patterns)
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
    """Download converted output as ZIP from output/ folder."""
    # Find latest migration output
    output_base = Path(__file__).parent.parent / 'output'
    output_dirs = list(output_base.glob(f'migration_*'))
    
    if not output_dirs:
        return jsonify({'error': 'No migration output found'}), 404
    
    latest = max(output_dirs, key=lambda p: p.stat().st_mtime)
    
    # Create temp zip
    temp_dir = Path(tempfile.gettempdir())
    zip_path = temp_dir / f'converted_{job_id}.zip'
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for file_path in latest.rglob('*'):
            if file_path.is_file():
                z.write(file_path, file_path.relative_to(latest))
    
    return Response(
        zip_path.read_bytes(),
        mimetype='application/zip',
        headers={
            'Content-Disposition': f'attachment; filename=converted_{job_id}.zip'
        }
    )


def clear_output_folder():
    """Clear output/ folder contents but keep Python files."""
    output_base = Path(__file__).parent.parent / 'output'
    if not output_base.exists():
        output_base.mkdir(parents=True, exist_ok=True)
        return
    
    for item in output_base.iterdir():
        # Skip Python files
        if item.is_file() and item.suffix == '.py':
            continue
        # Skip __pycache__ directories
        if item.is_dir() and item.name == '__pycache__':
            continue
        try:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
                log.info(f"Removed output directory: {item.name}")
            else:
                item.unlink()
                log.info(f"Removed output file: {item.name}")
        except Exception as e:
            log.warning(f"Could not remove {item}: {e}")


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
    
    # Run Flask with reloader disabled to prevent interruptions during conversion
    app.run(
        debug=True,
        host='0.0.0.0',
        port=5000,
        threaded=True,
        use_reloader=False
    )
