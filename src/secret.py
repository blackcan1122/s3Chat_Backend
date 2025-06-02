import secrets

def generate_secret_id(length=32):
    return secrets.token_hex(length)