
## Scenario tang

### 1. Tang reachable
- console login at 79s, data+docker active: **True**
```
Starting HAOS data partition unlock (network key)...
[INFO] Key provider: tang
[INFO] Data partition unlocked with the tang key (attempt 1)
Finished HAOS data partition unlock (network key).
```
### 2. Tang down at boot, started 3 min later
- Tang down for 180s after the prompt (prompt seen: True)
- console login at 276s, data+docker active: **True**
```
[WARN] Unlock attempt 5 (tang) failed, retrying in 60s
Error communicating with server http://10.0.2.2:8888
Nothing to read on input.
[WARN] Unlock attempt 6 (tang) failed, retrying in 60s
[INFO] Data partition unlocked with the tang key (attempt 7)
Finished HAOS data partition unlock (network key).
```
### 3. Tang replaced by a server with other keys
- after 2 min: recovery prompt shown: True, data unlocked (console login seen): **False** (expected False)
### 4. Server keys rotated (key directory now: ['.9jVjXwzAUjl24hPZEfY2KuRHlKZOO8MXwWbTwLCB6N4.jwk', '._sW6pE8FkNlII4scG_d_3w51Hi0xbqn4nBb21vOky2E.jwk', 'D8uLZptkQhMUy7s4dZbhpWE2kJuWeI1pCr8ZOoN8tE4.jwk', '_dWHCHEPfzbY2OZspQg4UDYzjCJuhvPyRcoS-fb-fqY.jwk'])
Old keys are kept as hidden files, so the existing key.jwe must still work:
- console login at 67s, data+docker active: **True**
```
Starting HAOS data partition unlock (network key)...
[INFO] Key provider: tang
[INFO] Data partition unlocked with the tang key (attempt 1)
Finished HAOS data partition unlock (network key).
```
