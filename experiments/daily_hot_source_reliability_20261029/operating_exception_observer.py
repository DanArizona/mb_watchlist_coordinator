"""Capture the original outer owner's swallowed error, only after it occurs."""
import ast
import copy
from datetime import timezone
import inspect
import json
from pathlib import Path
import textwrap

RECEIPT='operating-owner-error.json'
CAPTURE_NAME='_diagnostic_capture_operating_error'


def capture(owner,error,phase):
    frames=[];tb=error.__traceback__
    while tb is not None:
        module=tb.tb_frame.f_globals.get('__name__','')
        # The frozen proof's stop callback is test code. Retain its frame so
        # an observer/callback failure can be distinguished from runtime I/O.
        if (module.startswith(('mb_watchlist_coordinator.','mb_market_data.','test_'))
                or module in ('_hot_trace_control_fixture','pathlib','pathlib._local')):
            frames.append({'module':module,'function':tb.tb_frame.f_code.co_name,'line':tb.tb_lineno})
        tb=tb.tb_next
    def codes(failure):
        return {'error_type':type(failure).__name__,'error_module':type(failure).__module__,
            'errno':getattr(failure,'errno',None),'winerror':getattr(failure,'winerror',None),
            'sqlite_errorcode':getattr(failure,'sqlite_errorcode',None),
            'sqlite_errorname':getattr(failure,'sqlite_errorname',None),
            'filename':str(failure.filename) if isinstance(failure,OSError) and failure.filename is not None else None,
            'filename2':str(failure.filename2) if isinstance(failure,OSError) and failure.filename2 is not None else None}
    value={'contract':'daily-hot-operating-exception-v1',**codes(error),
        'observed_at_utc':owner.clock().astimezone(timezone.utc).isoformat(),'nonce':owner.binding['nonce'],
        'configuration_sha256':owner.binding['configuration_sha256'],
        'owner_phase_at_last_check':phase,'frames':frames[-20:],
        'failure_observed_before_original_handler':True,'failed_operation_retried':False}
    causes=[];failure=error;seen={id(error)}
    while len(causes)<4:
        failure=failure.__cause__ or (None if failure.__suppress_context__ else failure.__context__)
        if failure is None or id(failure) in seen:break
        seen.add(id(failure));causes.append(codes(failure))
    value['causes']=causes
    with (Path(owner.root)/RECEIPT).open('x',encoding='utf-8') as out:
        json.dump(value,out,indent=2);out.write('\n')


def guarded_capture(owner,error,phase):
    # Never replace the primary failure or its original cleanup path.
    try:capture(owner,error,phase)
    except BaseException:pass


def instrument(original):
    lines,start=inspect.getsourcelines(original)
    tree=ast.parse(textwrap.dedent(''.join(lines)))
    function=tree.body[0]
    if not isinstance(function,ast.FunctionDef) or function.name!='_run':
        raise ValueError('Original owner _run function required')
    before=ast.dump(tree,include_attributes=False)
    matches=[node for node in ast.walk(function) if isinstance(node,ast.ExceptHandler)
        and isinstance(node.type,ast.Name) and node.type.id=='Exception' and node.name=='error'
        and any(isinstance(child,ast.Constant) and child.value=='operating_evidence_or_launch_failed'
            for statement in node.body for child in ast.walk(statement))]
    if len(matches)!=1:raise ValueError('Exactly one original owner active-error handler required')
    handler=matches[0]
    call=ast.Expr(ast.Call(func=ast.Name(CAPTURE_NAME,ast.Load()),
        args=[ast.Name('self',ast.Load()),ast.Name('error',ast.Load()),ast.Name('phase',ast.Load())],keywords=[]))
    ast.copy_location(call,handler.body[0]);handler.body.insert(0,call)
    # Removing this single observation must recover the original entire AST.
    checked=copy.deepcopy(tree)
    checked_handler=next(n for n in ast.walk(checked) if isinstance(n,ast.ExceptHandler)
        and n.lineno==handler.lineno and n.col_offset==handler.col_offset)
    checked_handler.body.pop(0)
    if ast.dump(checked,include_attributes=False)!=before:raise ValueError('Unexpected owner instrumentation change')
    ast.fix_missing_locations(tree);ast.increment_lineno(tree,start-1)
    namespace=dict(original.__globals__);namespace[CAPTURE_NAME]=guarded_capture
    exec(compile(tree,original.__code__.co_filename,'exec'),namespace)
    observed=namespace['_run'];observed._owner_observer_original=original
    observed._owner_observer_original_ast=before
    return observed


def install(owner_type):
    original=owner_type._run
    if hasattr(original,'_owner_observer_original'):return original._owner_observer_original
    owner_type._run=instrument(original)
    return original
