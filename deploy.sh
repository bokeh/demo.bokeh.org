
git clone https://github.com/bokeh/bokeh.git
git clone https://github.com/bokeh/bokeh-demos.git

MINICONDA_VERSION=latest
MINICONDA="Miniconda-$MINICONDA_VERSION-Linux-x86_64"
MINICONDA_URL="http://repo.continuum.io/miniconda/$MINICONDA.sh"
wget $MINICONDA_URL
bash $MINICONDA.sh -b -p $HOME/miniconda

PATH=~/miniconda/bin/:$PATH

conda create -y -n bokeh -c bokeh/channel/dev bokeh
source activate bokeh

conda install -y pandas scikit-learn supervisor
