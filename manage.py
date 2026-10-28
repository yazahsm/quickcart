"""Local administrator bootstrap for an empty, non-demo installation."""
import argparse
import getpass
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from app.db import connect, initialize, password_hash


def main():
    parser = argparse.ArgumentParser(description='Create a Quick Cart administrator locally')
    parser.add_argument('email')
    parser.add_argument('--name', default='Administrator')
    args = parser.parse_args()
    email = args.email.strip().lower()
    if email.count('@') != 1 or '.' not in email.split('@')[-1] or any(c.isspace() for c in email) or len(email) > 254:
        parser.error('Enter a valid email address')
    if not 2 <= len(args.name.strip()) <= 80:
        parser.error('Name must be 2–80 characters')
    password = getpass.getpass('New password (10–128 characters): ')
    if not 10 <= len(password) <= 128:
        parser.error('Password must be 10–128 characters')
    if password != getpass.getpass('Confirm password: '):
        parser.error('Passwords do not match')
    path = os.environ.get('QUICKCART_DB', str(Path(__file__).resolve().parent / 'data' / 'quickcart.db'))
    initialize(path)
    try:
        with closing(connect(path)) as db, db:
            db.execute('INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)',
                       (args.name.strip(), email, password_hash(password), 'admin'))
    except sqlite3.IntegrityError:
        parser.error('That email is already registered; no account was changed')
    print(f'Administrator created: {email}')


if __name__ == '__main__':
    main()
