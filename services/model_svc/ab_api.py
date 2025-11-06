"""
HTTP API for managing A/B tests.
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

from model_router import get_router


class ABTestAPIHandler(BaseHTTPRequestHandler):
    """HTTP handler for A/B test management."""
    
    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        
        router = get_router()
        manager = router.ab_test_manager
        
        if path == '/ab-tests':
            # List all tests
            tests = manager.list_tests()
            self._send_json_response(tests)
        
        elif path.startswith('/ab-tests/'):
            test_id = path.split('/')[-1]
            
            if path.endswith('/metrics'):
                # Get metrics for a test
                metrics = router.get_test_metrics(test_id)
                self._send_json_response(metrics)
            else:
                # Get specific test
                test = manager.get_test(test_id)
                if test:
                    self._send_json_response(test.to_dict())
                else:
                    self._send_error(404, "Test not found")
        
        elif path == '/ab-tests/active':
            # Get active test
            test = manager.get_active_test()
            if test:
                self._send_json_response(test.to_dict())
            else:
                self._send_json_response(None)
        
        else:
            self._send_error(404, "Not found")
    
    def do_POST(self):
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == '/ab-tests':
            # Create new test
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            data = json.loads(body)
            
            try:
                test_id = self.server.router.ab_test_manager.create_test(
                    name=data['name'],
                    description=data.get('description', ''),
                    variants=data['variants'],
                    start_date=data.get('start_date'),
                    end_date=data.get('end_date')
                )
                self._send_json_response({'test_id': test_id}, status=201)
            except Exception as e:
                self._send_error(400, str(e))
        else:
            self._send_error(404, "Not found")
    
    def do_PUT(self):
        """Handle PUT requests."""
        parsed = urlparse(self.path)
        path_parts = parsed.path.split('/')
        
        if len(path_parts) == 3 and path_parts[0] == '' and path_parts[1] == 'ab-tests':
            test_id = path_parts[2]
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            data = json.loads(body)
            
            success = self.server.router.ab_test_manager.update_test(test_id, **data)
            if success:
                self._send_json_response({'status': 'updated'})
            else:
                self._send_error(404, "Test not found")
        else:
            self._send_error(404, "Not found")
    
    def do_DELETE(self):
        """Handle DELETE requests."""
        parsed = urlparse(self.path)
        path_parts = parsed.path.split('/')
        
        if len(path_parts) == 3 and path_parts[0] == '' and path_parts[1] == 'ab-tests':
            test_id = path_parts[2]
            success = self.server.router.ab_test_manager.delete_test(test_id)
            if success:
                self._send_json_response({'status': 'deleted'})
            else:
                self._send_error(404, "Test not found")
        else:
            self._send_error(404, "Not found")
    
    def _send_json_response(self, data, status=200):
        """Send JSON response."""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def _send_error(self, status, message):
        """Send error response."""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'error': message}).encode())
    
    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


def run_ab_test_api(port: int = 9001):
    """Run the A/B test API server."""
    server_address = ('', port)
    httpd = HTTPServer(server_address, ABTestAPIHandler)
    httpd.router = get_router()
    print(f'[ab_test_api] A/B Test API running on port {port}')
    httpd.serve_forever()

