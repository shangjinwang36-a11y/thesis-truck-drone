def sub(path, old, new):
    s = open(path, encoding='utf-8', newline='').read()
    for nl in ('\n', '\r\n'):
        o = old.replace('\r\n', '\n').replace('\n', nl); n = new.replace('\r\n', '\n').replace('\n', nl)
        c = s.count(o)
        if c == 1:
            open(path, 'w', encoding='utf-8', newline='').write(s.replace(o, n)); return
        if c > 1: raise AssertionError(f'not unique ({c}): {old[:60]!r}')
    raise AssertionError(f'not found in {path}: {old[:80]!r}')
