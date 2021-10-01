#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Ivan Vladimir Meza Ruiz 2018
# GPL 3.0

# imports
import yaml
from rich.console import Console
from rich.jupyter import print as rich_print
import os.path
import sys
import re
import time
import datetime
import importlib
from tinydb import TinyDB, Query
from collections import OrderedDict
import asyncio
import websockets
import websocket
import json
import requests


#local imports

# Import plugins
# TODO make a better system for plugins
# from plugins import random_greeting
# TODO make a better system for filters
from .filters import *
from .escaped_commands import *
from .audio import pull_latest, sr_google, audio_state, start_listening, stop_listening, enable_tts, enable_audio_listening, tts

re_conditional_else = re.compile(r"if (?P<conditional>.*) then (?P<cmd>(?:solve|say|input|loop_slots|stop|exit|post|get|put).*) else (?P<else_cmd>(?:solve|say|input|loop_slots|stop|exit|post|get|put).*)")
re_conditional = re.compile(r"if (?P<conditional>.*) then (?P<cmd>(?:solve|say|input|loop_slots|stop|exit|post|get|put).*)")
re_while = re.compile(r"while (?P<conditional>.*) then (?P<cmd>(solve|say|input|loop_slots|stop|exit|post|get|put).*)")
re_input = re.compile(r"input (?P<id>[^ ]+)(?: *\| *(?P<filter>\w+)(?P<args>.*)?$)?")
re_slot = re.compile(r"set_slot (?P<id>[^ ]+) +(?P<val>[^|]*)(?: *\| *(?P<filter>\w+)(?P<args>.*)?$)?")
re_set = re.compile(r"set_slot (?P<id>[^ ]+) +(?P<val>.*)$")
re_request = re.compile(r"(?P<type>put|get|post) (?P<api_name>[^ ]+) +(?P<extra_url>[^ ]+) +(?P<json>.+ )? *(?P<slot_name>[^ ]+)$")
re_escaped_command = re.compile(r"\\(?P<command>[^ ]+)(?P<args>.*)?$")

CONVERSATIONS={}

class Conversation:
    def __init__(self, filename,
            client_id=None,
            **config):
        """ Creates a conversation from a file"""
        #Variables
        self.verbose_=config.get("verbose",False)
        self.console=Console(record=True)
        self.path = os.path.dirname(filename)
        self.basename = os.path.basename(filename)
        self.modulename = os.path.splitext(self.basename)[0]
        self.strategies = {}
        self.contexts = {}
        self.plugins = config.get('plugins',{})
        self.package = ".".join(['plugins'])
        self.script = []
        self.slots = OrderedDict()
        self.history = []
        self.system_name = config.get('system_name',"SYS")
        self.user_name = config.get('user_name',"USR")
        self.erase_memory = config.get('erase_memory',False)
        self.nlps = {}
        self.pause = False
        self.language_google=config.get("tts_google_language","es-us")
        self.voice_local=config.get("tts_local_voice","spanish-latin-am")
        self.channels = config.get('channels',2)
        self.tts = config.get('tts',None)
        self.host = config.get('host','127.0.0.1')
        self.port = config.get('port',5000)
        self.IS={}
        self.url_apis={}
        self.speech_recognition = config.get('speech_recognition',None)
        self.dirplugins = config.get('dirplugins','plugins')
        self.isfilename = os.path.join(self.path,config.get('isfilenama','is.json'))
        if not self.path in sys.path:
            sys.path.append(os.path.join(self.path,config.get('dirplugins','plugins')))
        with open(filename, 'r', encoding="utf-8") as stream:
            try:
                definition=yaml.safe_load(stream)
            except yaml.YAMLError as exc:
                self.console.print(exc)
        self.load_conversation(definition)
        self.thread = None
        self.samplerate = int(config.get('samplerate',48000))
        self.device = config.get('device',None)
        self.audios_tts_db_name = os.path.join(
                self.path,
                config.get('audios_dir','audios'),
                config.get('audios_tts_db','audios_tts.tinydb'))
        self.speech_recognition_dir = os.path.join(
                self.path,
                config.get('audios_dir','audios'),
                config.get('speech_recognition_dir','speech_recognition'))
        os.makedirs(self.speech_recognition_dir, exist_ok=True)
        self.tts_dir = os.path.join(
                self.path,
                config.get('audios_dir','audios'),
                config.get('tts_dir','tts'))
        os.makedirs(self.tts_dir, exist_ok=True)
        if self.tts:
            self.verbose("Loading audios tts db",self.audios_tts_db_name)
            self.audios_tts_db = TinyDB(self.audios_tts_db_name)
        else:
            self.audios_tts_db = None
        self.conversation_id=None
        self.client=None
        if client_id: # TODO: Clever way for ids
            self.client_id=client_id
            self.conversation_id=client_id+1
        self.webclient_sid=None

    def set_thread(self,thread):
        self.thread = thread

    def set_idd(self,idd):
        self.idd= idd

    def set_webclient_sid(self,sid):
        self.webclient_sid = sid

    def start(self):
        time.sleep(0.8)
        if self.thread:
            self.thread.start()

    def stop(self):
        if self.client:
            pass
            #self.client.emit('finished',{'webclient_sid':self.webclient_sid,'idd':self.idd},namespace="/cv")
        if self.thread:
            sys.exit()

    def pause(self):
        self.pause=True

    def update_(self,conversation):
        self.contexts[conversation.modulename]=conversation
        self.strategies.update(conversation.strategies)
        self.verbose(f"[green]Setting conversation[/green] [bold]{conversation.modulename}[/bold]")

    def _load_conversations(self,conversations,path="./"):
        for conversation in conversations:
            conversation=os.path.join(path,conversation)
            conversation_=Conversation(filename=conversation,
                    **{
                        'plugins':self.plugins,
                        'tts':self.tts,
                    }
                    )
            self.verbose(f"[green]Conversation file loaded:[/green] [bold]{conversation}[/bold]")
            self.update_(conversation_)
            self.verbose(f"[green]Conversation file loaded:[/green] [bold]{conversation}[/bold]")

    def _load_plugings(self,plugins_):
        for plugin in plugins_:
            self.verbose("Importing plugin",plugin)
            thisplug = importlib.import_module(plugin)
            self.plugins[plugin]=thisplug

    def _load_strategies(self,strategies):
        for strategy,script in strategies.items():
            self.verbose("Setting strategy",strategy)
            self.strategies[strategy]=script

    def _load_url_apis(self,url_apis):
        for api_name,url in url_apis.items():
            self.verbose("Load APIs",api_name)
            self.url_apis[api_name]=url

    def _load_dbs(self,dbs,path="."):
        for dbname,loading_script in dbs.items():
            loading_script=loading_script.strip()
            self.verbose("Creating db",dbname)
            if loading_script.startswith("import"):
                bits=loading_script.split()
                db=[]
                if bits[0] == 'import_csv':
                    import csv
                    dbfile=os.path.join(path,bits[1])
                    self.verbose("Loading csv",dbfile)
                    with open(dbfile, encoding="utf-8") as csv_file:
                        csv_reader = csv.reader(csv_file, delimiter=',')
                        line_count = 0
                        for row in csv_reader:
                            if line_count == 0:
                                self.verbose("Column names are "," ".join(row),dbname)
                                line_count += 1
                            else:
                                line_count += 1
                                db.append(row)
            try:
                self.slots['db'][dbname]=db
            except KeyError:
                self.slots['db']={}
                self.slots['db'][dbname]=db


    def _load_is(self,isname):
        self.verbose("Loading IS",isname)
        if self.erase_memory:
            self.IS={}
        else:
            try:
                with open(isname,encoding="utf-8") as json_file:
                    self.IS = json.load(json_file)
            except FileNotFoundError:
                self.IS={}
        self.slots.update(self.IS)

    def _load_slots(self,slots):
        for slot in slots:
            self.slots[slot]=None

    def _load_settings(self,settings):
        if 'name' in settings:
            self.system_name=settings['name'] # Deprecated, print an error
        if 'system_name' in settings:
            self.system_name=settings['system_name']
        if 'user_name' in settings:
            self.user_name=settings['user_name']
        if 'system_name_html' in settings:
            self.system_name_html=settings['system_name_html']
        if 'user_name_html' in settings:
            self.user_name_html=settings['user_name_html']
        if 'console_style' in settings:
            self.console=Console(style=settings['console_style'])

    def load_conversation(self,definition):
        """ Loads a full conversation"""
        if 'conversations' in definition:
            self._load_conversations(definition['conversations'],path=self.path)
        if 'slots' in definition:
            self._load_slots(definition['slots'])

        # TODO: a better pluggin system
        try:
            self._load_plugings(definition['plugins'])
        except KeyError:
            pass
        try:
            self._load_url_apis(definition['url_apis'])
        except KeyError:
            pass
        try:
            self._load_strategies(definition['strategies'])
        except KeyError:
            pass
        try:
            self._load_dbs(definition['dbs'],path=self.path)
        except KeyError:
            pass
        if self.isfilename:
            self._load_is(self.isfilename)
        try:
            self._load_settings(definition['settings'])
        except KeyError:
            pass
        self.regex=definition.get('regex',{})
        self.script=definition['script']

    def verbose(self,*args,**kargs):
        """ Prints message in verbose mode """
        if self.verbose_:
            self.console.print(*args,**kargs)

    def add_turn(self,user,cmds):
        self.history.append((user,cmds))

    def solve_(self,*args):
        """ Command solve to look for an specific strategy """
        if len(args)!=1:
            raise ArgumentError('Expected an argument but given more or less')
        self.verbose("Trying to solve")
        try:
            if args[0] in self.contexts:
                self.current_context=self.contexts[args[0]]
                slots_tmp=OrderedDict(self.current_context.slots)
                plugins_tmp=OrderedDict(self.current_context.plugins)
                slots_tmp_ = self.slots
                plugins_tmp_ = self.plugins
                self.slots=self.current_context.slots
                self.plugins=self.current_context.plugins
                self.slots.update(slots_tmp_)
                self.plugins.update(plugins_tmp_)
                status=self.execute_(self.current_context.script)
                self.current_context.plugins=plugins_tmp
                self.current_context=self
                return status
            elif args[0] in self.strategies:
                return self.execute_(self.strategies[args[0]])
            else:
                raise KeyError('The solving strategy was not found', args[0])
        except KeyError:
            raise KeyError('The solving strategy was not found',args[0])


    def eval_(self,cmd):
        """ evaluate python expression"""
        loc=dict(self.slots)
        loc.update(self.plugins)
        result=eval(cmd,globals(),loc)
        if result:
            self.execute_line_(result)
        else:
            pass

    def execute__(self,cmd):
        """ execute python command"""
        print("CMD",cmd)
        exec(cmd)

    def say_(self,cmd):
        """ Say command """
        result=eval(cmd,globals(),self.slots)
        MSG=f"{self.system_name}: [bold]{result}[/bold]"
        self.console.print(MSG)
        if self.client:
            spk=getattr(self,'system_name_html',self.system_name)
            data={'cmd':'say','spk':spk,'msg':f'<b>{result}</b>','client_id':self.client_id}
            self.client.send(json.dumps(data))
        if self.tts:
            stop_listening()
            tts(result)
            start_listening()
        else:
            pass

    def input_(self,line):
        """ Input command """
        self.input=None
        m=re_input.match(line)

        if m:
            self.console.print(f"{self.user_name}:",end="")
            if self.client and not self.speech_recognition:
                spk=getattr(self,'user_name_html',self.user_name)
                self.client.send(json.dumps({"cmd":"activate input",'spk':spk,"client_id":self.client_id}))
                while not self.input:
                    time.sleep(0.1)
                result=self.input
                self.console.print(f"[bold]{result}[/bold]",end="")

            elif self.speech_recognition:
                start_listening()
                filename=None
                while not filename:
                    time.sleep(1)
                    filename=pull_latest()
                result=sr_google(filename)
                if self.client:
                    data={'spk':self.name, "msg": result, 'webclient_sid':self.webclient_sid}
                    self.client.emit('input log',data,namespace="/cv")
            else:
                result=input()
                m_=re_escaped_command.match(result)
                while m_:
                    ## If a escaped command was introduced
                    if m_.group("command") == "slot":
                        ec_slot(self,m_.group("args").strip().split())
                    if m_.group("command") == "slots":
                        ec_slots(self)

                    self.console.print(f"{self.user_name}: [bold]",end="")
                    result=input()
                    m_=re_escaped_command.match(result)

            idd=m.group('id')
            raw=result
            if m.group('filter'):
                fil=m.group('filter')
                args=m.group('args').split()
                slots_ = dict(self.slots)
                slots_['args']=args
                slots_['self']=self
                result=eval('{}(self,"{}",*args)'.format(fil,result),globals(),slots_)
            if not idd == '_': 
                self.slots[idd]=result
            else:
                if isinstance(result,dict):
                    self.slots.update(result)

    def loop_slots_(self):
        """ Loop slots until fill """
        for slot in [name for name, val in self.slots.items() if val is None]:
            self.execute_line_("solve {}".format(slot))

    def conditional_(self,line):
        """ conditional execution """
        if " else " in line:
            m=re_conditional_else.match(line)
            else_=True
        else:
            m=re_conditional.match(line)
            else_=False
        if m:
            conditional=m.group('conditional')
            try:
                result=eval(conditional,globals(),self.slots)
            except NameError:
                self.console.print("[red]False because variable not defined[\red]")
                result=True
            if not result and else_:
                cmd=m.group('else_cmd')
                return self.execute_line_(cmd)
            elif result:
                cmd=m.group('cmd')
                return self.execute_line_(cmd)

    def request_(self,line):
        """ request execution """
        m=re_request.match(line)
        if m:
            api_url=self.url_apis[m.group("api_name")]
            url=f'{api_url}{m.group("extra_url")}'
            if m.group('json'):
                json_=dict(eval("{{{}}}".format(m.group("json")),globals(),self.slots))
            request_type=m.group('type')
            if request_type=="post":
                response=requests.post(url,json=json_)
                self.slots[m.group("slot_name")]=response.json()
            if request_type=="get":
                response=requests.get(url)
                self.slots[m.group("slot_name")]=response.json()


    def while_(self,line):
        """ while execution """
        m=re_while.match(line)
        last=None
        if m:
            conditional=m.group('conditional')
            cmd=m.group('cmd')
            try:
                result=eval(conditional,globals(),self.slots)
            except NameError:
                self.console.print("[red]False because variable not defined[\red]")
                result=True
            if result:
                last=self.execute_line_(cmd)
                self.execute_line_(line)
            return last

    def add_slot_(self,arg):
        self.slots[arg]=None

    def set_slot_(self,line):
        m=re_slot.match(line)
        if m:
            idd=m.group('id')
            cmd="{}".format(m.group('val'))
            result=eval(cmd,globals(),self.slots)
            raw=result
            if m.group('filter'):
                fil=m.group('filter')
                args=m.group('args').split()
                slots_ = dict(self.slots)
                slots_['args']=args
                slots_['self']=self
                result=eval('{}(self,"{}",*args)'.format(fil,result),globals(),slots_)
            if not idd == '_': 
                self.slots[idd]=result
            else:
                if isinstance(result,dict):
                    self.slots.update(result)



    def del_slot_(self,arg):
        del self.slots[arg]

    def remember_(self,arg):
        self.IS[arg]=self.slots[arg]
        with open(self.isfilename,"w", encoding="utf-8") as json_file:
            json.dump(self.IS,json_file)

    def stop_(self):
        return 1

    def EXIT_(self):
        return 0

    def empty_slot_(self,line):
        self.slots[line]=None

    def execute_line_(self,line):
        line=line.strip()
        self.verbose("Command",line)
        if self.slots:
            self.verbose("SLOTS:", ", ".join(["{}:{}".format(x,y)
                                                                for x,y in self.slots.items()]))
        if line.startswith('solve '):
            cmd,args=line.split(maxsplit=1)
            return self.solve_(*args.split())
        elif line.startswith('execute '):
            cmd,args=line.split(maxsplit=1)
            self.execute__(args)
        elif line.startswith('say '):
            cmd,args=line.split(maxsplit=1)
            self.say_(args)
        elif line.startswith('input '):
            self.input_(line)
        elif line.startswith('loop_slots'):
            self.loop_slots_()
        elif line.startswith('post ') or line.startswith('put ') or line.startswith('get ') :
            return self.request_(line)
        elif line.startswith('if '):
            return self.conditional_(line)
        elif line.startswith('while '):
            return self.while_(line)
        elif line.startswith('add_slot'):
            cmd,args=line.split(maxsplit=1)
            self.add_slot_(args)
        elif line.startswith('empty_slot '):
            cmd,args=line.split(maxsplit=1)
            self.empty_slot_(args)
        elif line.startswith('set_slot '):
            self.set_slot_(line)
        elif line.startswith('del_slot '):
            cmd,args=line.split(maxsplit=1)
            self.del_slot_(args)
        elif line.startswith('remember '):
            cmd,args=line.split(maxsplit=1)
            self.remember_(args)
        elif line.startswith('stop'):
            return self.stop_()
        elif line.startswith('exit'):
            return self.EXIT_()
        else:
            return self.eval_(line)

    def execute_(self,script):
        status=None
        for line in script:
            if not self.pause:
                status=self.execute_line_(line)
                if not status is None: # finish dialogue
                    break
            else:
                time.sleep(0.1)
        if status == 0:
            return 0


    def execute(self):
        if self.conversation_id:
            self.client= websocket.WebSocket()
            self.client.connect(f"ws://{self.host}:{self.port}/cv/{self.conversation_id}")

        if self.speech_recognition:
            enable_audio_listening(
                    samplerate=self.samplerate,
                    device=self.device,
                    host=self.host,
                    port=self.port,
                    channels = self.channels,
                    speech_recognition_dir=self.speech_recognition_dir,
                    )
        if self.tts:
            enable_tts(
                engine=self.tts,
                tts_dir=self.tts_dir,
                language=self.language_google,
                voice=self.voice_local,
                db=self.audios_tts_db
                )
        self.current_context=self
        self.execute_(self.script)
        if self.client:
            self.stop()


