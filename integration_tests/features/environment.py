#import logging

#def before_all(context):
#    logging.basicConfig(filemode='w', filename="/data/users/kkolman/integration_tests/polar2grid/integration_tests/behave.log", level=logging.INFO, format='%(levelname)s: %(message)s')
#    context.logger = logging.getLogger(__name__)

import sys
    
def after_feature(context, feature):
    if context.failed:
        sys.exit(1)



