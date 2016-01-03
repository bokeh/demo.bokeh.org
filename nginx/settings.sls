{% set NUM_SERVERS = salt['pillar.get']('bokeh:num_servers', 4)|int %}
{% set PUBLIC_IP = salt['cmd.run']('curl http://169.254.169.254/latest/meta-data/public-ipv4 2> /dev/null ')  %}
