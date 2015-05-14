import copy
import re
from functools import partial
from ..helpers import is_channel_name
from ..message import Message
from ..signals import message_in, message_out, on_exception
from .base import BaseIdleModule
from .mixins import ConfigMixin
from .utils import parse_command


class BaseResponder(ConfigMixin, BaseIdleModule):
    """Inherit from this class to quickly create a module which reacts to users'
    messages. Each incomming PRIVMSG is dispatched to the `handle_privmsg` method
    and all incoming messages are dispatched to `handle_msg` method. If a message
    starts with a command_prefix defined in config it will be also sent to
    a proper handler, for example `command_help`.

    Example config:

        "base_responder": {
            "command_prefix": "."
        }
    """

    # Prefix for command handlers. For example `command_help` is a handler for
    # messages starting with .help
    handler_prefix = 'command_'

    # Don't send description of the .help command - normally each module which
    # is based on this class would respond to such request and flood a user with
    # messages. This should be set to False only in one module (by default in
    # module meta). Note that this parameter is a terrible workaround. The
    # problem is caused by the fact that modules do not have direct access to
    # each another, so it is not possible to query others modules for commands.
    # Each module has to report them separately, and in effect the same command
    # had to be defined in all modules.
    ignore_help = True

    # A module is expected to store the config in
    # config['module_config'][config_namespace][config_name]
    config_namespace = None
    config_name = None

    # This is the default config for this class
    base_default_config = {
        "command_prefix": "."
    }

    # Default config for the class which inherits from BaseResponder
    default_config = {}

    def __init__(self, config):
        super(BaseResponder, self).__init__(config)
        self._commands = self._get_commands_from_handlers()
        message_in.connect(self.on_message_in)

        self.register_default_config(self.base_default_config)
        self.register_default_config(self.default_config)
        self.register_config('botnet', 'base_responder')
        if self.config_namespace and self.config_name:
            self.register_config(self.config_namespace, self.config_name)

    def _get_commands_from_handlers(self):
        """Generates a list of supported commands from defined handlers."""
        commands = []
        for name in dir(self):
            if name.startswith(self.handler_prefix):
                attr = getattr(self, name)
                if hasattr(attr, '__call__'):
                    command_name = name[len(self.handler_prefix):]
                    if not (self.ignore_help and command_name == 'help'):
                        commands.append(command_name)
        return commands

    def _dispatch_message(self, msg):
        # Main handler
        self.handle_msg(msg)
        if msg.command == 'PRIVMSG':
            # PRIVMSG handler
            self.handle_privmsg(msg)
            # Command-specific handler
            if self.is_command(msg):
                # First word of the last parameter:
                cmd_name = msg.params[-1].split(' ')[0]
                cmd_name = cmd_name.strip(self.config_get('command_prefix'))
                func = self._get_command_handler(cmd_name)
                if func is not None:
                    func(msg)

    def _get_command_handler(self, cmd_name):
        """Returns a handler for a command."""
        handler_name = self.handler_prefix + cmd_name
        return getattr(self, handler_name, None)

    def on_message_in(self, sender, msg):
        """Handler for a message_in signal. Dispatches the message to the
        per-command handlers and the main handler.
        """
        try:
            self._dispatch_message(msg)
        except Exception as e:
            on_exception.send(self, e=e)
            raise

    def is_command(self, priv_msg, command_name=None, command_prefix=None):
        """Returns True if the message text starts with a prefixed command_name.
        If command_name is None this function will simply check if the message
        is prefixed with a command prefix. By default the command prefix
        defined in the config is used but you can ovverida it by passing the
        command_prefox parameter.
        """
        if command_prefix is None:
            cmd = self.config_get('command_prefix')
        else:
            cmd = command_prefix

        if command_name:
            cmd += command_name
            return priv_msg.params[-1].split()[0] == cmd
        else:
            return priv_msg.params[-1].startswith(cmd)

    def respond(self, priv_msg, text, pm=False):
        """Send a text in response to a message. Text will be automatically
        sent to a proper channel or user.

        priv_msg: Message object to which we are responding.
        text: Response text.
        pm: If True response will be a private message.
        """
        # If this is supposed to be sent as a private message or was sent in
        # a private message to the bot respond also in private message.
        if pm or not is_channel_name(priv_msg.params[0]):
            target = priv_msg.nickname
        else:
            target = priv_msg.params[0]
        response = Message(command='PRIVMSG', params=[target, text])
        message_out.send(self, msg=response)

    def get_all_commands(self):
        """Should return a list of strings containing all commands supported by
        this module.
        """
        return self._commands

    @parse_command([('command_names', '*')])
    def command_help(self, msg, args):
        """If COMMAND is specified sends detailed help for the commands in a
        private message.

        Syntax: help [COMMAND ...]
        """
        if len(args.command_names) > 0:
            # Display help for a specific command
            for name in args.command_names:
                if self.ignore_help and name == 'help':
                    continue
                lines = []
                handler = self._get_command_handler(name)
                if handler:
                    # Header
                    res = 'Module %s, help for `%s`: ' % (self.__class__.__name__,
                                                          name)
                    # Docstring
                    help_text = handler.__doc__
                    if help_text:
                        res += ' '.join(help_text.splitlines())
                    else:
                        res += 'No help available.'

                    res = re.sub(' +', ' ', res)
                    lines.append(res)

                for line in lines:
                    self.respond(msg, line, pm=True)

    def handle_msg(self, msg):
        """Handler called when a message is received."""
        pass

    def handle_privmsg(self, msg):
        """Handler called when a message with a PRIVMSG command is received."""
        pass
