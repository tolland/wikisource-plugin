# Sourced (not executed) by inject-gradle-proxy.sh's generated command prefix.
#
# The remote Claude sandbox exposes an outbound proxy but the exact env var
# name it uses isn't known/stable, so this discovers it at run time instead
# of hardcoding a guess: prefers the conventional http_proxy/https_proxy
# family (any case), then falls back to any *PROXY* var holding a URL.
# Normalizes to both cases of http_proxy/https_proxy/no_proxy (different
# tools read different casings) and to GRADLE_OPTS -D system properties,
# since the JVM ignores the env vars and only honors -Dhttp(s).proxyHost/Port.
__cc_gradle_proxy_setup() {
    local url="" var name value

    for var in https_proxy HTTPS_PROXY http_proxy HTTP_PROXY all_proxy ALL_PROXY; do
        if [ -n "${!var:-}" ]; then
            url="${!var}"
            break
        fi
    done

    if [ -z "$url" ]; then
        while IFS='=' read -r name value; do
            case "$name" in
            *PROXY* | *proxy*)
                case "$value" in
                http://* | https://* | socks5://*)
                    url="$value"
                    break
                    ;;
                esac
                ;;
            esac
        done < <(env)
    fi

    [ -z "$url" ] && return 0

    local no=""
    for var in no_proxy NO_PROXY; do
        if [ -n "${!var:-}" ]; then
            no="${!var}"
            break
        fi
    done

    export http_proxy="$url" https_proxy="$url" HTTP_PROXY="$url" HTTPS_PROXY="$url"
    export no_proxy="$no" NO_PROXY="$no"

    local hostport host port
    hostport="${url#*://}"
    hostport="${hostport%%/*}"
    host="${hostport%%:*}"
    port="${hostport##*:}"
    [ "$port" = "$host" ] && port=80

    local nonproxy_hosts=""
    if [ -n "$no" ]; then
        nonproxy_hosts=$(echo "$no" | tr ',' '|')
    fi

    local proxy_opts="-Dhttp.proxyHost=$host -Dhttp.proxyPort=$port -Dhttps.proxyHost=$host -Dhttps.proxyPort=$port"
    [ -n "$nonproxy_hosts" ] && proxy_opts="$proxy_opts -Dhttp.nonProxyHosts=$nonproxy_hosts"

    export GRADLE_OPTS="${GRADLE_OPTS:+$GRADLE_OPTS }$proxy_opts"
}

__cc_gradle_proxy_setup
