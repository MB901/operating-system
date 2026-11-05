#!/bin/bash
# Tang server helper for the test harness (test only).
#   tang-server.sh init   <keydir>             create a new key pair
#   tang-server.sh serve  <keydir> [port]      run tangd behind socat (foreground)
#   tang-server.sh rotate <keydir>             rotate keys (old ones are kept
#                                              hidden, so old JWEs still work)
#   tang-server.sh thp    <keydir>             print the signing key thumbprint
#   tang-server.sh jwe    <keydir> <url> <in> <out> [port]
#                                              encrypt <in> for the server at
#                                              <url>, pinned to its current adv
set -euo pipefail

cmd="$1"; dir="$2"
case "${cmd}" in
    init)
        mkdir -p "${dir}"
        /usr/libexec/tangd-keygen "${dir}"
        ;;
    serve)
        port="${3:-8888}"
        exec socat "TCP-LISTEN:${port},reuseaddr,fork" "EXEC:/usr/libexec/tangd ${dir}"
        ;;
    rotate)
        /usr/libexec/tangd-rotate-keys -d "${dir}"
        ;;
    thp)
        tang-show-keys 2> /dev/null || true
        for k in "${dir}"/*.jwk; do
            if jose jwk use -i "${k}" -u verify 2> /dev/null; then
                jose jwk thp -i "${k}"
            fi
        done
        ;;
    jwe)
        url="$3"; in="$4"; out="$5"; port="${6:-8888}"
        adv="$(mktemp)"
        # The adv is fetched locally and passed to clevis, so clevis does not
        # need to reach <url> and does not ask for confirmation.
        curl -sf "http://127.0.0.1:${port}/adv" -o "${adv}"
        clevis encrypt tang "{\"url\":\"${url}\",\"adv\":\"${adv}\"}" < "${in}" > "${out}"
        rm -f "${adv}"
        ;;
    *)
        echo "unknown command ${cmd}" >&2
        exit 2
        ;;
esac
