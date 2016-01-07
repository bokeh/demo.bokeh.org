#1/bin/bash

NUM_SERVERS=6

while getopts "hs:" x; do
    case "$x" in
       h)
            echo "usage: $0 [options]

Installs Miniconda/Nginx/Bokeh Server

    -s           Number of Nginx Servers to run with unique ports, default is 6
    -h           print this help message and exit
"
            exit 2
	    ;;
	s)
  	    NUM_SERVERS="$OPTARG"
	    ;;
        ?)
            echo "Error: did not recognize option, please try -h"
            exit 1
            ;;
   esac
done

echo "Installing Miniconda, Nginx (with $NUM_SERVERS servers) and Bokeh Server"

MINICONDA_VERSION=latest
MINICONDA="Miniconda-$MINICONDA_VERSION-Linux-x86_64"
MINICONDA_URL="http://repo.continuum.io/miniconda/$MINICONDA.sh"
wget -N $MINICONDA_URL
bash $MINICONDA.sh -b -p $HOME/miniconda

PATH=~/miniconda/bin/:$PATH

conda create -y -n bokeh -c bokeh/channel/dev bokeh
source activate bokeh

conda install -y pandas scikit-learn supervisor

PREFIX=~/miniconda
CONDA=$PREFIX/bin/conda
IP=`curl http://169.254.169.254/latest/meta-data/local-ipv4`
SALT_ENV=$PREFIX/envs/salt
SUPERVISOR_ENV=$PREFIX/envs/supervisor
BOKEH_ENV=$PREFIX/envs/bokeh
HOSTNAME=`hostname`

mkdir -p ~/log

$CONDA create -y -n salt python=2.7 salt -c anaconda-cluster
$CONDA create -y -n supervisor python=2.7 supervisor -c anaconda-cluster

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
log_file: /opt/anaconda/envs/salt/var/log/salt/minion
EOF



mkdir -p $SALT_ENV/srv/pillar/bokeh
cat << EOF > $SALT_ENV/srv/pillar/bokeh/init.sls
bokeh:
  num_servers: $NUM_SERVERS
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

sudo $SALT_ENV/bin/salt-key -y -a $HOSTNAME

cp -r bokeh nginx $SALT_ENV/srv/salt
sudo $SALT_ENV/bin/salt '*' state.sls nginx
sudo $SALT_ENV/bin/salt '*' state.sls bokeh
