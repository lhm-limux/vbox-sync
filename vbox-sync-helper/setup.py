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
      scripts=['vbox-sync', 'vbox-invoke', 'vbox-makecfg', 'vbox-dispose'],
      data_files=[('share/man/man1', ['vbox-invoke.1', 'vbox-makecfg.1']),
                  ('share/man/man8', ['vbox-sync.8', 'vbox-dispose.8'])],
      package_data={'itomig': ['vbox-sync-admin.glade']},
     )
