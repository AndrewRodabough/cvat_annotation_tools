import os
import sys

def get_int_env_var(name: str, default: int | None = None) -> int:
    """Get an environment variable and convert to int, or exit with error."""
    value = os.getenv(name)
    if not value:
        if default is not None:
            return default
        print(f"Error: {name} must be set in environment variables or .env file.", file=sys.stderr)
        sys.exit(1)
    try:
        return int(value)
    except ValueError:
        print(f"Error: {name}='{value}' is not a valid integer.", file=sys.stderr)
        sys.exit(1)

def get_str_env_var(name: str, default: str | None = None) -> str:
    """Get an environment variable as string, or exit with error."""
    value = os.getenv(name)
    if not value:
        if default is not None:
            return default
        print(f"Error: {name} must be set in environment variables or .env file.", file=sys.stderr)
        sys.exit(1)
    return value