"""Start Quick Cart from any working directory."""
import argparse
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Quick Cart local server')
    parser.add_argument('--demo', action='store_true', help='Seed demo accounts on an empty database')
    parser.add_argument('--port', type=int, default=8010)
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args()
    from app.db import seed_demo
    if args.demo:
        path = os.environ.get('QUICKCART_DB', str(ROOT / 'data' / 'quickcart.db'))
        print('Demo data created.' if seed_demo(path) else 'Database already has users; demo seed skipped.')
    import uvicorn
    uvicorn.run('app.main:app', host=args.host, port=args.port)
