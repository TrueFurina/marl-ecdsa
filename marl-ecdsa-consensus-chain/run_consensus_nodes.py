"""Run 3 independent loopback node processes; stop with Ctrl+C."""
import sys,subprocess,signal
from visualization.distributed_consensus import init_network,serve
if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--node':serve(sys.argv[2])
    else:
        init_network()
        ps=[subprocess.Popen([sys.executable,__file__,'--node',f'node-{i}']) for i in range(1,4)]
        print('Started three independent nodes. Ctrl+C to stop.',flush=True)
        try:
            for p in ps:p.wait()
        except KeyboardInterrupt:pass
        finally:
            for p in ps:p.terminate()
            for p in ps:
                try:p.wait(timeout=3)
                except subprocess.TimeoutExpired:p.kill()
