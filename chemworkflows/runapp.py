import os
import sys
import json

import dill

import yaml
import pyccc
from pyccc.workflow.runner import SerialCCCRunner, SerialRuntimeRunner

from .apps import vde, MMminimize

APPNAMES = {'minimize': MMminimize.minimization,
            'vde': vde.vde}


def main(args):
    outdir = make_output_dir(args)

    if args.restart:  # restarts branch here!!!
        restart_workflow(args, outdir)
        sys.exit(0)

    engine, RunnerClass = get_execution_env(args)
    inputjson = process_input_file(args.inputfile)
    app = APPNAMES[args.appname]

    runner = RunnerClass(app,
                         engine=engine,
                         molecule_json=inputjson)

    if args.setoutput:
        set_ui_outputs(runner)

    if args.preprocess:
        run_preprocessing(runner, outdir)
    else:  # run the whole thing
        run_workflow(runner, outdir)


def run_workflow(runner, outdir):
    runner.run()

    print 'DONE. Output directory:'
    print "    ", os.path.abspath(outdir)

    with open(os.path.join(outdir,'workflow_state.dill'), 'w') as outfile:
        dill.dump(runner, outfile)

    write_outputs(runner, outdir)


def write_outputs(runner, outdir):
    """ Write a finished workflow's outputs to disk
    """
    for name in runner.workflow.outputfields:
        value = runner.getoutput(name)

        filebase = os.path.join(outdir, name)
        if isinstance(value, basestring):
            with open(filebase, 'w') as outfile:
                print >> outfile, value
        elif isinstance(value, dict):
            with open(filebase+'.json', 'w') as outfile:
                json.dump(value, outfile)
        elif hasattr(value, 'put'):
            value.put(filebase)
        elif hasattr(value, 'read'):
            with open(filebase, 'w') as outfile:
                print >> outfile, value.read
        else:
            with open(filebase+'.dill', 'w') as outfile:
                dill.dump(value, outfile)


def restart_workflow(args, outdir):
    with open(args.inputfile, 'r') as infile:
        runner = dill.load(infile)

    engine, RunnerClass = get_execution_env(args)
    assert RunnerClass is runner.__class__

    if args.setoutput:
        set_ui_outputs(runner, args)

    print ' ----   RESTARTING WORKFLOW "%s"   ----\n' % runner.workflow.name

    run_workflow(runner, outdir)


def set_ui_outputs(runner, args):
    """ Set the outputs of frontend tasks

    ``args.setoutput`` is a list tasks and output files of the form
    ``"[taskname]=[output json file]"``
    """
    for item in args.setoutput:
        taskname, filename = item.split('=')
        task = runner.tasks[taskname]
        with open(filename, 'r') as infile:
            taskoutput = json.load(infile)

        print 'Setting output of UI task "%s" to contents of %s' % (taskname, filename)
        runner.tasks[taskname] = pyccc.workflow.MockUITask(task.spec, taskoutput)
    print


def run_preprocessing(runner, outdir):
    t = runner.preprocess()

    print 'FINISHED preprocessing. Output directory:'
    print "    ", os.path.abspath(outdir)

    resultjson = {}
    for field in t.outputs:
        if field == 'pdbstring':
            with open(os.path.join(outdir, 'prep.pdb'), 'w') as outfile:
                print >> outfile, t.getoutput('pdbstring')
        else:
            resultjson[field] = t.getoutput(field)

    with open(os.path.join(outdir, 'prep.json'), 'w') as outfile:
        json.dump(resultjson, outfile)
    with open(os.path.join(outdir, 'workflow_state.dill'), 'w') as outfile:
        dill.dump(runner, outfile)


def make_output_dir(args):
    """ Create a local output directory to hold the results. If the output directory is not
    explicitly specified, always create a new, unique directory. Otherwise, put the outputs
    wherever requested.
    """
    if args.outputdir is None:
        idir = 0
        while os.path.exists('%s.out.%d' % (args.appname, idir)):
            idir += 1
        outdir = '%s.out.%d' % (args.appname, idir)
        os.mkdir(outdir)

    else:
        outdir = args.outputdir
        if not os.path.exists(outdir):
            os.mkdir(outdir)

    print 'Running workflow "%s" with input "%s."\nOutputs will be written to "%s".'%(
        args.appname, args.inputfile, outdir)
    return outdir


def get_execution_env(args):
    """ Figure out where the workflow will run and how we'll run it
    """
    runner = SerialCCCRunner
    if args.localdocker:
        assert not args.here
        engine = pyccc.Docker()
    elif args.here:
        runner = SerialRuntimeRunner
        engine = None
    else:
        engine = get_engine()
    return engine, runner


def get_engine():
    server = os.environ.get('CCC', None)
    if not server:
        print 'WARNING: No CCC server set in environment variable "$CCC", using default.'
        server = 'ccc.bionano.autodesk.com:9000'

    print 'Using CCC server: %s' % server
    return pyccc.engines.CloudComputeCannon(server)


def process_input_file(inputfile):
    """ Figure out whether we're being passed a file, a description of a file, or just raw JSON
    """
    try:
        jsraw = _get_json(inputfile)
    except ValueError:
        pass
    else:
        inputjson = json.loads(jsraw)
        return inputjson

    ext = inputfile.split('.')[-1]
    if ext in ('js', 'json', 'yml', 'yaml'):
        with open(inputfile, 'r') as infile:
            inputjson = yaml.load(infile)
    else:
        with open(inputfile, 'r') as infile:
            inputjson = {'filename': inputfile,
                         'content': infile.read()}
    return inputjson


def _get_json(s):
    s = s.strip()
    while s and s[0] == s[-1] and s[0] in ('"', "'"):
        s = s[1:-1].strip()

    if not s or s[0] != '{' or s[-1] != '}':
        raise ValueError()
    else:
        return s
