-- Run after create-slot on the fresh independent clone. With no database
-- CREATE and no business-table ownership this must fail with 42501.
SET SESSION AUTHORIZATION :"publisher";
CREATE PUBLICATION :"publication" FOR TABLE
    fixture.customers, fixture.orders, fixture.order_items, fixture.payments;
