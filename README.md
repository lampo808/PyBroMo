Overview
=======

PyBroMo is a simulator for confocal single-molecule fluorescence experiments.

The program simulates 3-D Brownian motion trajectories and fluorescent
emission of an arbitrary number of molecules diffusing in a simulation volume. 
The excitation volume is defined numerically or analytically (3-D Gaussian 
shape). Molecules diffusing through the excitation volume will emit at a rate
proportional to the excitation intensity.

PyBroMo allows to simulate smFRET experiments with desired FRET efficiency.
Timestamps for donor and acceptor channel are generated.

The PSF is numerically precomputed on a regular grid using the 
[PSFLab](http://onemolecule.chem.uwm.edu/software) software and interpolated 
during the Brownian motion simulation in order to compute the emission 
intensity. Alternatively a simple analytical Gaussian PSF can be also used.

The user documentation is in the form of a series of IPython Notebooks.

Environment
==========

PyBroMo is written in the python programming language using the standard 
scientific stack of libraries (numpy, scipy, matplotlib).

Usage examples are given as 
[IPython Notebook](http://ipython.org/notebook.html) files. This is an 
interactive environment that allows to mix rich text, math and graphics with 
(executable) code, similarly to the Mathematica environment. An static version
of the notebooks can be read following the link provided at the end of this
 page.

Moreover the IPython environment allows to easily build and use a cluster 
for parallel computing. This feature allows to leverage the computing power
of multiple computers (different desktop in a lab) greatly enhancing
the length and span of simulation that can be performed. Examples on how to
perform parallel simulation are provided as well.

For more information for python and science:

* [Python Scientific Lecture Notes](http://scipy-lectures.github.io/)


#Installation


##MS Windows

In order to use the software you need to install a scientific python
distribution like [Anaconda](https://store.continuum.io/cshop/anaconda/).
The free version of Anaconda includes all the needed dependencies.
 
After that, you can start using the simulator
launching an IPython Notebook server in the PyBroMo notebook folder
(see the following paragraph) and executing the examples.

###Configuring IPython Notebook

If you put PyBroMo in "C:\PyBroMo" then the notebooks folder will be 
"C:\PyBroMo\notebooks".

Just right click on the IPython Notebook icon -> Properties and paste 
this folder in "Start in". Apply and close.

Now double click on the icon and a browser should pop up showing the list
of notebooks. Chrome browser is suggested.

##Linux and Mac OS X

On Linux or Mac OS X you can use the Anaconda distribution.

Otherwise this are the requirements you have to make sure are properly 
installed:

 - python 2.7.x
 - IPython 1.x
 - matplotlib 1.3.x or greater
 - numpy/scipy (any recent version)
 - modern browser (Chrome suggested)
 
#Usage examples

The following links will open (a static version of) the notebooks provided
with PyBroMo. These collection serves both as usage examples and user guide:



