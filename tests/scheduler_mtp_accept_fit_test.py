import unittest


from sim.scheduler import scheduler_sim


class SchedulerMtpAcceptFitTest(unittest.TestCase):
    def test_trace_summary_derives_pos_cond_accept_prob_and_geom_fit(self) -> None:
        # draft_len=2 implies accept_len in [1..3]
        draft_len = 2

        routes = []
        # 50% reject => accept_len=1
        for i in range(50):
            routes.append(scheduler_sim.TokenRoute(t_ms=float(i), cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,), mtp_accept_len=1))
        # 30% accept 1 draft token => accept_len=2
        for i in range(50, 80):
            routes.append(scheduler_sim.TokenRoute(t_ms=float(i), cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,), mtp_accept_len=2))
        # 20% accept 2 draft tokens => accept_len=3
        for i in range(80, 100):
            routes.append(scheduler_sim.TokenRoute(t_ms=float(i), cls=scheduler_sim.LatencyClass.BATCH, candidates=(0,), mtp_accept_len=3))

        out = scheduler_sim.trace_summary_jsonable(routes, mtp_draft_len=draft_len)
        derived = out.get("mtp_accept_derived")
        self.assertIsInstance(derived, dict)
        pos = derived.get("pos_cond_accept_prob")
        self.assertIsInstance(pos, list)
        self.assertEqual(len(pos), draft_len)
        self.assertAlmostEqual(float(pos[0]), 0.5, places=6)
        self.assertAlmostEqual(float(pos[1]), 0.4, places=6)

        fit = derived.get("fit_geom")
        self.assertIsInstance(fit, dict)
        self.assertAlmostEqual(float(fit.get("accept_prob", 0.0)), 0.5, places=6)
        self.assertAlmostEqual(float(fit.get("accept_decay", 0.0)), 0.8, places=6)
        self.assertAlmostEqual(float(fit.get("pred_mean_accept_len", 0.0)), 1.7, places=6)


if __name__ == "__main__":
    unittest.main()

