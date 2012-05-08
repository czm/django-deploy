# coding: utf-8
from django import template
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand, CommandError
from django.template import Context, Template
from django.template.loader import get_template
from django.utils.datastructures import SortedDict
from django.utils.encoding import smart_unicode,force_unicode
from django.utils.html import strip_tags
from optparse import make_option
from pprint import pprint
import datetime
import os, sys, pwd, grp, logging


# init logging stuff
log = logging.getLogger('management_commands')
log.setLevel(logging.ERROR)
ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter(u"%(asctime)s :: %(levelname)s :: %(message)s"))
log.addHandler(ch)
log.propagate = 0

""" # uncomment to test log messages
log.debug("debug message")
log.info("info message")
log.warn("warn message")
log.error("error message")
log.critical("critical message")
"""

DEPLOY_FILES_PATH = getattr(settings,'DEPLOY_FILES_PATH',os.path.join(settings.PROJECT_PATH,'deploy','files'))

# these files will be parsed with following vars:
# module_name: the module where this conf is created, normally the project short name


# To this template mapping context will be applyet to each FILE_FINAL_NAME, all with lower case except PATH stuff
# TEMPLATE_FILE should be a file in path like normal templates used in views.
TEMPLATE_MAPPING = {
    # KEY:                  (TEMPLATE_FILE,                             FILE_FINAL_NAME)
    'CELERYBEAT_CONF':      ('deploy/celerybeat.conf.template',         'celerybeat.conf'),
    'CELERYBEAT_INIT':      ('deploy/celerybeat-init.d.template',       'celerybeat_%(MODULE_NAME)s_%(VENV_NAME)s'),
    'CELERYD_CONF':         ('deploy/celeryd.conf.template',            'celeryd.conf'),
    'CELERYD_INIT':         ('deploy/celeryd-init.d.template',          'celeryd_%(MODULE_NAME)s_%(VENV_NAME)s'),
    'INSTALL_ROOT_SCRIPT':  ('deploy/install_init_scripts.sh.template', 'install_init_scripts.sh'),
    'NGINX_CONF':           ('deploy/nginx.conf.template',              'nginx.conf'),
    'START_UWSGI_SCRIPT':   ('deploy/start_uwsgi.template',             'start_uwsgi'),
    'UWSGI_INIT':           ('deploy/uwsgi-init.d.template',            'uwsgi_%(MODULE_NAME)s_%(VENV_NAME)s'),
    'UWSGI_CONF':           ('deploy/uwsgi.ini.template',               'uwsgi.ini'),
}

class Command(BaseCommand):

    help = """Parse deploy templates to create deploy files for Nginx, uWSGI and Celery."""

    option_list = BaseCommand.option_list + (
        make_option('--uid',
            action='store',
            dest='uid',
            default=pwd.getpwuid(os.getuid())[0],
            help=u"User under daemons will run. Defaults to current user.",
        ),
        make_option('--gid',
            action='store',
            dest='gid',
            default=grp.getgrgid(os.getgid())[0],
            help=u"Group under daemons will run. Defaults to current group.",
        ),
        make_option('--site-name',
            action='store',
            dest='site_name',
            default=False,
            help=u"Site name will be used in server virtualhost name entry.",
        ),
        make_option('--site-port',
            action='store',
            dest='site_port',
            default=80,
            help=u"Port under site will run. Default is 80."
        ),
    )

    #### SCRIPT HANDLING #####################################################
    def handle(self, *args, **options):
        """ execute the command """
        if args and args[0] == 'help':
            return self.print_help(sys.argv[1],'-h')

        # set log messages
        if int(options.get('verbosity')) > 0: log.setLevel(logging.INFO)
        if options.get('verbosity') in (1,2,'1','2'): log.setLevel(logging.DEBUG)

        if not options.get('site_name'):
            raise CommandError,u"To script works you should send as paramater at least --site-name <site_name.com>"

        module_name = self.__class__.__module__.split('.')[0]
        CELERYD_CONF_NAME = 'celeryd_%(module_name)s.conf' % {'module_name':module_name,}
        CELERYBEAT_CONF_NAME = 'celerybeat_%(module_name)s.conf' % {'module_name':module_name,}
        UWSGI_INI = 'uwsgi.ini'

        CONTEXT_VARS = {
            'DEPLOY_FILES_PATH': DEPLOY_FILES_PATH,
            'MODULE_NAME': module_name,
            'CELERYBEAT_CONF':os.path.join(DEPLOY_FILES_PATH,CELERYBEAT_CONF_NAME),
            'CELERYD_CONF': os.path.join(DEPLOY_FILES_PATH,CELERYD_CONF_NAME),
            'UWSGI_INI': os.path.join(DEPLOY_FILES_PATH,UWSGI_INI),
            'SITE_NAME': options.get('site_name'),
            'SITE_PORT': options.get('site_port'),
            'UID':options.get('uid'),
            'GID':options.get('gid'),
            'PROJECT_PATH': settings.PROJECT_PATH,
            'VENV_PATH': os.environ['VIRTUAL_ENV'],
            'VENV_NAME': os.environ['VIRTUAL_ENV'].split('/')[-1]
        }

        CONTEXT_VARS_LOWER = CONTEXT_VARS.copy()
        CONTEXT_VARS_LOWER.update({
            'MODULE_NAME': CONTEXT_VARS['MODULE_NAME'].lower(),
            'SITE_NAME': CONTEXT_VARS['SITE_NAME'].lower(),
            'VENV_NAME': CONTEXT_VARS['VENV_NAME'].lower()
            })

        # check if path exist
        if not os.path.exists(DEPLOY_FILES_PATH):
            os.makedirs(DEPLOY_FILES_PATH,0775)

        CONTEXT_VARS['INIT_FILES'] = {}
        CONTEXT_VARS['CONF_FILES'] = {}

        for name,(template_name,final_name) in TEMPLATE_MAPPING.items():
            if 'init.d' in template_name:
                CONTEXT_VARS['INIT_FILES'][name] = final_name % CONTEXT_VARS_LOWER
            else:
                CONTEXT_VARS['CONF_FILES'][name] = final_name % CONTEXT_VARS_LOWER

        pprint(CONTEXT_VARS)

        for name,(template_name,final_name) in TEMPLATE_MAPPING.items():

            final_name = final_name % CONTEXT_VARS_LOWER

            log.info(u"Processing %s ...",final_name)
            tpl = get_template(template_name)
            parsed = tpl.render(Context(CONTEXT_VARS))

            f = open(os.path.join(DEPLOY_FILES_PATH,final_name),'w')
            f.write(parsed)
            f.close()

            log.info(u'File created: %s ...',final_name)
            os.chown(f.name,pwd.getpwnam(CONTEXT_VARS['UID'])[2],grp.getgrnam(CONTEXT_VARS['GID'])[2])
            os.chmod(f.name,0664)

            if 'init.d' in template_name or 'install' in template_name:
                os.chmod(f.name,0775)