import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from xiangqi_variants.jieqi_night import round_seed, run_campaign


class JieqiNightTests(unittest.TestCase):
    def options(self, root):
        initial = root / 'initial'; initial.mkdir()
        for ext in ['pt', 'onnx', 'json']:
            (initial / f'candidate.{ext}').write_bytes(b'initial')
        return SimpleNamespace(out=root / 'campaign', initial=initial, hours=1,
            round_minutes=30, nodes=128, steps=2000, pairs=8, device='cpu')

    def test_rounds_use_new_seeds_and_chain_completed_weights(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.options(Path(tmp)); now=[100.0]; calls=[]
            def runner(options):
                calls.append(options)
                self.assertEqual(options.deadline_override, 3700)
                model=options.out / 'model'; model.mkdir()
                (model / 'candidate.pt').write_bytes(str(len(calls)).encode())
                (options.out / 'summary.json').write_text(json.dumps({'phase':'complete',
                    'onnxSha256':str(len(calls)), 'trainGames':8, 'evaluation':{}}))
                now[0]+=1800
            state=run_campaign(args, runner=runner, clock=lambda:now[0])
            self.assertEqual(len(calls),2)
            self.assertEqual(calls[1].initial,calls[0].out / 'model')
            self.assertNotEqual(calls[0].seed_offset,calls[1].seed_offset)
            self.assertEqual(state['phase'],'budget-finished')
            self.assertEqual(state['deadline'],3700)

    def test_interrupt_resume_preserves_deadline_and_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.options(Path(tmp)); now=[100.0]; seen=[]
            def interrupted(options):
                seen.append(options.seed_offset); now[0]+=30
                raise KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):
                run_campaign(args, runner=interrupted, clock=lambda:now[0])
            state=json.loads((args.out/'night.json').read_text())
            self.assertEqual(state['phase'],'interrupted')
            with self.assertRaises(KeyboardInterrupt):
                run_campaign(args, runner=interrupted, clock=lambda:now[0])
            restored=json.loads((args.out/'night.json').read_text())
            self.assertEqual(restored['deadline'],state['deadline'])
            self.assertEqual(seen,[round_seed(0),round_seed(0)])
            args.nodes=256
            with self.assertRaisesRegex(ValueError,'configuration mismatch'):
                run_campaign(args, runner=interrupted, clock=lambda:now[0])

    def test_expired_campaign_never_starts_new_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.options(Path(tmp)); now=[100.0]
            def interrupted(_):
                raise KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):
                run_campaign(args, runner=interrupted, clock=lambda:now[0])
            now[0]=3701
            state=run_campaign(args, runner=lambda _:self.fail('expired campaign ran'), clock=lambda:now[0])
            self.assertEqual(state['phase'],'budget-finished')

    def test_seed_domains_do_not_overlap_across_rounds(self):
        ranges=[(round_seed(i)+3000000,round_seed(i)+6010000) for i in range(200)]
        self.assertTrue(all(a[1]<b[0] for a,b in zip(ranges,ranges[1:])))
        with self.assertRaises(ValueError): round_seed(200)


if __name__=='__main__': unittest.main()
