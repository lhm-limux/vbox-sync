from distutils.core import setup
setup(name='vbox-sync-helper',
      version='0.1',
      author='Philipp Kern',
      author_email='philipp.kern@itomig.de',
      classifiers=[
        'License :: OSI Approved :: European Union Public License',
        'Programming Language :: Python'
        ],
      packages=['itomig'],
      scripts=['vbox-sync', 'vbox-invoke'],
     )
