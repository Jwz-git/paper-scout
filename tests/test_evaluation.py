from backend.app.evaluation import EvaluationCase, evaluate_cases


def test_manual_quality_metrics_keep_unknown_and_sample_denominators():
    case = EvaluationCase(topic='Artificial counting fixture', sample_kind='artificial', report_id='fake-report',
        reference_paper_ids=['a', 'b', 'b'], retrieved_relevance={'a':True, 'c':False, 'd':None},
        field_correctness={'f1':True, 'f2':None}, citation_support={'c1':False},
        subproblem_coverage={'s1':None}, notes='Arithmetic only, not a research evaluation')
    result = evaluate_cases([case])['cases'][0]
    assert result['retrieval_precision'] == {'numerator':1, 'denominator':2, 'unknown':1, 'value':.5}
    assert result['sample_recall']['value'] == .5
    assert result['field_accuracy']['denominator'] == 1
    assert result['citation_support']['value'] == 0
    assert result['subproblem_coverage']['value'] is None
