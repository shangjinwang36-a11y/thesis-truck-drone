"""CRLF 安全的文件编辑辅助：读入时转 LF，写回时恢复原换行."""
def load(path):
    raw = open(path, newline='', encoding='utf-8').read()
    crlf = '\r\n' in raw
    return raw.replace('\r\n', '\n'), crlf

def save(path, text, crlf):
    if crlf:
        text = text.replace('\n', '\r\n')
    open(path, 'w', newline='', encoding='utf-8').write(text)

def sub(path, old, new, count=1):
    t, c = load(path)
    assert old in t, f"pattern not found in {path}: {old[:60]!r}"
    t = t.replace(old, new, count)
    save(path, t, c)
