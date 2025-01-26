import os, threading
from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command

from ...npm import NPM, NPMException
from ...utils import get_tailwind_src_path, install_pip_package
from ...validate import ValidationError, Validations

from tailwind import get_config

class Command(BaseCommand):

    def add_arguments(self, parser):
        self.validate = Validations()
        self.stdout.write("Sending output to stdout...")
        # Make each "verb" a subcommand, so that additional arguments can easily be supplied
        # only to some, but not to others
        subparsers = parser.add_subparsers(
            title="tailwind-commands",
            required=True,
        )
        # the init verb needs options that none of the others require
        init_parser = subparsers.add_parser(
            "init",
            help="initialize django-tailwind app",
        )
        init_parser.add_argument(
            "--no-input",
            action="store_true",
            help="Initializes Tailwind project without user prompts",
        )
        init_parser.add_argument(
            "--app-name",
            help="Sets default app name on Tailwind project initialization",
        )
        init_parser.set_defaults(method=self.handle_init)

        # the runserver verb needs to collect the arguments that it will pass to the runserver command
        runserver_parser = subparsers.add_parser(
            "runserver",
            help="start whatching css changes, then run the django development server",
        )
        runserver_parser.add_argument(
            "addrport", nargs="?", help="Optional port number, or ipaddr:port"
        )
        runserver_parser.add_argument(
            "--ipv6",
            "-6",
            action="store_true",
            dest="use_ipv6",
            help="Tells Django to use an IPv6 address.",
        )
        runserver_parser.add_argument(
            "--nothreading",
            action="store_false",
            dest="use_threading",
            help="Tells Django to NOT use threading.",
        )
        runserver_parser.add_argument(
            "--noreload",
            action="store_false",
            dest="use_reloader",
            help="Tells Django to NOT use the auto-reloader.",
        )
        runserver_parser.set_defaults(method=self.handle_runserver)

        # For all of the other commands, all we need are help text and a handler method
        npm_commands = {
            "install": ("install npm packages necessary to build tailwind css", self.handle_install),
            "build": ("compile tailwind css into production css", self.handle_build),
            "start": ("start watching css changes for dev", self.handle_start),
            "check-updates": ("list possible updates for tailwind css and its dependencies", self.handle_check_updates),
            "update": ("update tailwind css and its dependencies", self.handle_update)
        }
        for command_name, (help_text, handler) in npm_commands.items():
            subcommand_parser = subparsers.add_parser(
                command_name,
                help = help_text
            )
            subcommand_parser.set_defaults(method=handler)


    def validate_app(self):
        try:
            self.validate.has_settings()
            app_name = get_config("TAILWIND_APP_NAME")
            self.validate.is_installed(app_name)
            self.validate.is_tailwind_app(app_name)
        except ValidationError as err:
            raise CommandError(err)


    def handle(self, *args, method, **options):
        if str(method.__name__) != "handle_init":
            # These will never work until after `manage.py tailwind init` has completed
            self.validate_app()
            self.npm = NPM(cwd=get_tailwind_src_path(get_config("TAILWIND_APP_NAME")))
        method(*args, **options)

    def handle_init(self, **options):
        try:
            from cookiecutter.main import cookiecutter
        except ImportError:
            self.stderr.write("Cookiecutter is not found, installing...")
            try:
                install_pip_package("cookiecutter")
            except:
                raise CommandError("Neither pip nor cookiecutter was available. Unable to initialize tailwind app")
            from cookiecutter.main import cookiecutter

        try:
            app_path = cookiecutter(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                output_dir=os.getcwd(),
                directory="app_template",
                no_input=options["no_input"],
                overwrite_if_exists=False,
                extra_context={
                    "app_name": options["app_name"].strip()
                    if options.get("app_name")
                    else "theme"
                },
            )

            app_name = os.path.basename(app_path)

            self.stdout.write(
                self.style.SUCCESS(
                    f"Tailwind application '{app_name}' "
                    f"has been successfully created. "
                    f"Please add '{app_name}' to INSTALLED_APPS in settings.py, "
                    f"then run the following command to install Tailwind CSS "
                    f"dependencies: `python manage.py tailwind install`"
                )
            )
        except Exception as err:
            raise CommandError(err)

    def handle_runserver(self, **options):
        # per https://code.djangoproject.com/ticket/8085 our custom runserver code should only be run when
        # os.environ["RUN_MAIN"] is set
        if not os.environ.get("RUN_MAIN", False):
            app_name = get_config("TAILWIND_APP_NAME")
            self.stdout.write(self.style.SUCCESS(
                f"Starting tailwindcss command to listen for changes to CSS classes according to configuration found in {app_name}"
            ))
            # Start tailwind in a background, daemonic thread so that it will watch for CSS class changes while the django dev
            # server is running, then terminate when the django dev server stops
            t = threading.Thread(target=self.npm_command, args=("run", "start"), daemon=True)
            t.start()
        
        # This calls whatever command resolves as `runserver` according to the django project config. That should be
        # the default django one for almost every app, and others need to be prepared to accept its options.
        return call_command("runserver", **options)
    
    def handle_install(self, **options):
        self.npm_command("install")

    def handle_build(self, **options):
        self.npm_command("run", "build")

    def handle_start(self, **options):
        self.npm_command("run", "start")

    def handle_check_updates(self, **options):
        self.npm_command("outdated")

    def handle_update(self, **options):
        self.npm_command("update")

    def npm_command(self, *args):
        try:
            self.npm.command(*args)
        except NPMException as err:
            raise CommandError(err)
        except KeyboardInterrupt:
            pass

