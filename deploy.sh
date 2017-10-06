#!/bin/bash

NUM_SERVERS=6
SERVER_NAME=`hostname`

while getopts "hsn:" x; do
    case "$x" in
       h)
            echo "usage: $0 [options]

Installs Miniconda/Nginx/Bokeh Server

    -s           Number of Nginx Servers to run with unique ports, default is 6
    -h           print this help message and exit
    -n		 name of host server
"
            exit 2
	    ;;
	s)
  	    NUM_SERVERS="$OPTARG"
	    ;;
	n)
  	    SERVER_NAME="$OPTARG"
	    ;;
        ?)
            echo "Error: did not recognize option, please try -h"
            exit 1
            ;;
   esac
done

echo "Installing Miniconda, Nginx (with $NUM_SERVERS servers) and Bokeh Server with host: $SERVER_NAME"

MINICONDA_VERSION=latest
MINICONDA="Miniconda3-$MINICONDA_VERSION-Linux-x86_64"
MINICONDA_URL="https://repo.continuum.io/miniconda/$MINICONDA.sh"
MINICONDA_DIR=$HOME/miniconda3
wget -N $MINICONDA_URL
if [ -d  $MINICONDA_DIR ]; then 
 echo "miniconda3 already installed"
else
 bash $MINICONDA.sh -b -p $MINICONDA_DIR 
fi

PATH=~/miniconda3/bin/:$PATH

if [ -d  $MINICONDA_DIR/envs/bokeh ]; then
  echo "bokeh env exists"
else
  conda create -q -y -n bokeh python
  conda install -c bokeh nodejs bokeh -q -y -n bokeh
  conda install -q -y numba pandas scikit-learn -n bokeh
fi

CONDA=$MINICONDA_DIR/bin/conda
IP=`curl http://169.254.169.254/latest/meta-data/local-ipv4`
SALT_ENV=$MINICONDA_DIR/envs/salt
SUPERVISOR_ENV=$MINICONDA_DIR/envs/supervisor
BOKEH_ENV=$MINICONDA_DIR/envs/bokeh
HOSTNAME=`hostname`

mkdir -p ~/log

if [ -d  $MINICONDA_DIR/envs/salt ]; then
  echo "salt env exists"
else
  $CONDA create -q -y -n salt python=2.7 salt -c conda-forge
fi

if [ -d  $MINICONDA_DIR/envs/supervisor ]; then
  echo "supervisor env exists"
else
  $CONDA create -q -y -n supervisor python=2.7 supervisor
fi

#grab sample data
$BOKEH_ENV/bin/python -c "import bokeh.sampledata; bokeh.sampledata.download()"

#set up supervisor directories
pushd $SUPERVISOR_ENV
mkdir -p var/run 
mkdir -p etc/supervisor/conf.d 
mkdir -p var/log/supervisor
popd


cat << EOF > $SALT_ENV/etc/salt/master

interface: $IP

log_level: debug
log_file: $SALT_ENV/var/log/salt/master

file_roots:
  base:
    - $SALT_ENV/srv/salt

pillar_roots:
  base:
    - $SALT_ENV/srv/pillar

EOF

cat << EOF > $SALT_ENV/etc/salt/minion

master: $IP

mine_functions:
  network.get_hostname: []
  network.interfaces: []
  network.ip_addrs: []
mine_interval: 2

log_level: debug
log_file: $SALT_ENV/var/log/salt/minion
EOF



mkdir -p $SALT_ENV/srv/pillar/bokeh
cat << EOF > $SALT_ENV/srv/pillar/bokeh/init.sls
bokeh:
  num_servers: $NUM_SERVERS
  server_name: $SERVER_NAME
EOF


sudo cat << EOF > $SALT_ENV/srv/pillar/top.sls
base:
  '*':
    - bokeh
EOF

sleep 1
if pgrep "salt-master" > /dev/null
then
    echo "salt-master already started"
else
    echo "starting salt-master"
    sudo $SALT_ENV/bin/salt-master -d
fi

# wait for master to come online
if pgrep "salt-minion" > /dev/null
then 
    echo "salt-minionalready started"
else
    echo "starting salt-minion"
    sleep 5
    sudo $SALT_ENV/bin/salt-minion -d
fi

## auto generate master/minion keys
#sudo $SALT_ENV/bin/salt-key --gen-keys=bokeh_salt_keys
#sudo cp bokeh_salt_keys.pub $SALT_ENV/etc/salt/pki/master/minions/
#sudo cp bokeh_salt_keys.pub bokeh_salt_keys.pem $SALT_ENV/etc/salt/pki/minion/

sudo $SALT_ENV/bin/salt-key -y -a $HOSTNAME*

cp -r bokeh nginx $SALT_ENV/srv/salt
sudo $SALT_ENV/bin/salt '*' state.sls nginx
sudo $SALT_ENV/bin/salt '*' state.sls bokeh

# Download Stock Data after git checkout
 sudo $BOKEH_ENV/bin/python /home/ec2-user/bokeh/examples/app/stocks/download_sample_data.py
