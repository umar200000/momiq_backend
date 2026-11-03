"""Release-one listing contract at the same validator used by HTTP writes."""
import copy
import unittest
import server


class ListingValidationTests(unittest.TestCase):
    def item(self, kind):
        return {'type':kind,'pets':['cat'],'price':500000,'active':True,'capacity':1,
                'location':{'lat':41.3,'lon':69.2,'address':'TEST location'}}

    def validate(self, item, housing='apartment'):
        return server.validate_listings({'housing':housing,'listings':[item]})

    def test_three_services_reject_other_types_and_invalid_price_or_location(self):
        for service in ('boarding','homeVisit','personal'):
            good=self.item(service)
            self.validate(good)
            for changes in [{'pets':['other']},{'pets':['cat','other']},{'pets':[]},
                            {'price':0},{'price':-1},{'price':True},{'price':1.5},
                            {'price':1000000000},
                            {'location':{'lat':True,'lon':69.2,'address':'TEST'}},
                            {'location':{'lat':41.3,'lon':69.2,'address':'x'*1001}}]:
                with self.subTest(service=service,changes=changes):
                    with self.assertRaises(ValueError):self.validate({**good,**changes})
            if service=='homeVisit':self.validate({**good,'pets':['dog','cat'],'location':None})
            else:
                for changes in [{'pets':['dog','cat']},{'location':None}]:
                    with self.assertRaises(ValueError):self.validate({**good,**changes})

    def test_capacity_duplicate_service_and_personal_exclusivity(self):
        good=self.item('boarding')
        for capacity in (0,2,True,1.5):
            with self.assertRaises(ValueError):self.validate({**good,'capacity':capacity})
        self.validate({**good,'capacity':3},'house')
        with self.assertRaises(ValueError):self.validate({**good,'capacity':4},'house')
        for items in [[good,copy.deepcopy(good)],[good,self.item('personal')]]:
            with self.assertRaises(ValueError):server.validate_listings({'housing':'house','listings':items})
        server.validate_listings({'housing':'house','listings':[{**good,'active':False},self.item('personal')]})


if __name__=='__main__':unittest.main()
