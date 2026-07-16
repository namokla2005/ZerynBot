"""run_dashboard.py — Start the Flask web dashboard."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from database import init_db
init_db()

from dashboard.app import app

if __name__ == "__main__":
    print("[Dashboard] Starting at http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
