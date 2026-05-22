import subprocess

def parse_nuclio(line: str):
    parts = line.split('|')

    out = []
    for part in parts:
        out.append(part.strip())
    
    return out

def get_nuclio_function_port(function_name: str) -> int:
    result = subprocess.run(["nuctl", "get", "function", function_name], capture_output=True, text=True)

    lines= result.stdout.split('\n')
    
    if not lines or len(lines) <= 1:
        return None

    header = lines[0]
    body = lines[1:]

    for index, word in enumerate(parse_nuclio(header)):
        if word == "NODE PORT":
            ports_index = index
        if word == "NAME":
            name_index = index


    if ports_index and name_index:
        for line in body:
            words = parse_nuclio(line)
            if words[name_index] == function_name:
                return int(words[ports_index])
            
    return None