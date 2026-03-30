def need(name: str, cfg: dict):
    if name not in cfg:
        raise ValueError(f"Missing required config key: {name}")
    return cfg[name]