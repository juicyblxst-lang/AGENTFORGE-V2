import unittest
from app.discovery import normalize, category_for

class DiscoveryTests(unittest.TestCase):
    def test_category_mapping(self):
        self.assertIn('rebalancing', category_for('automated portfolio rebalance'))
        self.assertIn('grid-trading', category_for('grid bot'))
        self.assertIn('yield-optimization', category_for('maximize APY'))
        self.assertIn('health-factor', category_for('liquidation health factor'))

    def test_identity_deduplication(self):
        raw={'items':[
            {'token_id':7,'owner_address':'0xabc','name':'A','services':[{'type':'A2A','endpoint':'https://a'}]},
            {'token_id':7,'owner_address':'0xabc','name':'A duplicate','services':[{'type':'A2A','endpoint':'https://a'}]},
            {'token_id':8,'owner_address':'0xdef','name':'B','services':[]},
        ]}
        agents=normalize(raw)
        self.assertEqual(len(agents),2)
        self.assertEqual(agents[0]['agentId'],'7')
        self.assertEqual(agents[0]['endpoints'][0]['url'],'https://a')

if __name__=='__main__': unittest.main()
