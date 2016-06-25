install-deps:
  pkg.installed:
    - pkgs:
      - nginx
      - git

copy-static-files:
  cmd.run:
    - name: cp -r `bokeh info --static` /srv/
    - user: root
    - group: root
    - env:
       - PATH: /bin:/usr/bin:/home/ec2-user/miniconda/envs/bokeh/bin

static-files:
  file.directory:
    - name: /srv/static
    - user: nginx
    - group: nginx
    - recurse:
      - user
      - group

index.html:
  file.managed:
    - name: /srv/demo.bokehplots.com/index.html
    - source: salt://nginx/templates/index.html
    - user: nginx
    - group: nginx
    - makedirs: true
    - recurse:
      - user
      - group


nginx-conf:
  file.managed:
    - name: /etc/nginx/conf.d/bokehdemoplots.conf
    - source: salt://nginx/templates/nginx.conf
    - template: jinja
    - user: root
    - group: root

nginx-service:
  service.running:
    - name: nginx
    - watch:
      - pkg: install-deps
      - file: nginx-conf


