@import <FileUpload/FileUpload.j>
@import "../Model/Page.j"


@implementation PageController : CPObject
{
    @outlet     UploadButton    imageUploadButton;
    @outlet     CPArrayController   pageArrayController;
}

- (id)initWithCoder:(CPCoder)aCoder
{
    if (self = [super init])
    {
        CPLog("Init with Coder called");
    }
}

- (IBAction)uploadFiles:(id)aSender
{
    CPLog("Upload files called");
}

- (void)createObjectsWithJSONResponse:(CPString)aResponse
{
    var createdPages = aResponse.pages;
    CPLog("Creating pages");
    [WLRemoteObject setDirtProof:YES];  // turn off auto-creation of pages since we've already done it.
    console.log(createdPages);

    pages = [Page objectsFromJson:createdPages];
    [pageArrayController addObjects:pages];

    [WLRemoteObject setDirtProof:NO];
}

- (void)uploadButton:(UploadButton)button didChangeSelection:(CPArray)selection
{
    CPLog("Did Change Selection");
    console.log(selection);
    [button submit];
}

- (void)uploadButton:(UploadButton)button didFailWithError:(CPString)anError
{
    CPLog("Did Fail");
    CPLog(anError);
}

- (void)uploadButton:(UploadButton)button didFinishUploadWithData:(CPString)response
{
    [button resetSelection];
    data = JSON.parse(response)
    [self createObjectsWithJSONResponse:data];
}

- (void)uploadButtonDidBeginUpload:(UploadButton)button
{
    CPLog("Did Begin Upload");
}

@end
