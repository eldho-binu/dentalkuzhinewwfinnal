import os
import sys
from werkzeug.serving import run_simple
from app import app

if __name__ == '__main__':
    print("🚀 Starting development server...")
    print("💡 Press Ctrl+C to stop")
    
    try:
        run_simple(
            hostname='127.0.0.1',
            port=5000,
            application=app,
            use_debugger=True,
            use_reloader=False,
            threaded=True
        )
    except KeyboardInterrupt:
        print("\n🛑 Development server stopped")
    except Exception as e:
        print(f"❌ Error: {e}")