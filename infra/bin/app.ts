import * as cdk from "aws-cdk-lib";
import { LinionsStack } from "../lib/linions-stack";
import { config } from "../config";

const app = new cdk.App();
new LinionsStack(app, config.stackName);
