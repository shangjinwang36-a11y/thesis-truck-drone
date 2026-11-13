def patch(path, old, new, count=1):
    s = open(path, newline='').read()
    crlf = '\r\n' in s
    if crlf:
        old = old.replace('\r\n','\n').replace('\n','\r\n'); new = new.replace('\r\n','\n').replace('\n','\r\n')
    assert s.count(old) >= 1, ('not found', path, old[:80])
    assert count == 0 or s.count(old) == count, ('count', s.count(old), old[:80])
    open(path, 'w', newline='').write(s.replace(old, new))
